import asyncio
import contextlib
import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.contenttypes.models import ContentType

from .execution import execute_snippet
from .models import CustomLogEntry, Host, SnippetExecution
from .ssh import get_host_route, open_ssh_connection

logger = logging.getLogger(__name__)


@database_sync_to_async
def _log_action(user, host_id, action):
    host = Host.objects.get(pk=host_id)

    CustomLogEntry.objects.create(
        content_type=ContentType.objects.get_for_model(Host),
        object_pk=str(host_id),
        object_id=host_id,
        object_repr=str(host),
        action=action,
        actor=user,
    )


class SSHConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        if not self.scope["user"].is_authenticated:
            await self.close()
            return

        self.host_id = self.scope["url_route"]["kwargs"]["host_id"]
        self._ssh_stack = None
        self._read_task = None
        self._connections = []
        await self.accept()

        try:
            route = await get_host_route(self.host_id)
        except Host.DoesNotExist:
            await self.send(text_data=json.dumps({"error": "Host not found"}))
            await self.close()
            return

        try:
            self._ssh_stack, connection = await open_ssh_connection(route)

            (
                self._writer,
                self._reader,
                self._err_reader,
            ) = await connection.open_session(term_type="xterm-256color")
            self._read_task = asyncio.ensure_future(self._read_ssh())
            await _log_action(
                self.scope["user"],
                self.host_id,
                CustomLogEntry.Action.CONNECT,
            )
        except Exception as e:
            logger.exception("SSH connection failed")
            await self.send(text_data=json.dumps({"error": str(e)}))
            await self.close()

    async def _read_ssh(self):
        """Read from SSH stdout/stderr and forward to WebSocket."""
        try:
            while True:
                tasks = []
                if not self._reader.at_eof():
                    tasks.append(asyncio.ensure_future(self._reader.read(4096)))
                if not self._err_reader.at_eof():
                    tasks.append(asyncio.ensure_future(self._err_reader.read(4096)))

                if not tasks:
                    break

                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

                for task in done:
                    data = task.result()
                    if data:
                        await self.send(
                            bytes_data=data.encode() if isinstance(data, str) else data
                        )

                # Cancel pending tasks
                for task in tasks:
                    if not task.done():
                        task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await task
        except asyncio.CancelledError, OSError:
            pass
        finally:
            await self.close()

    async def receive(self, text_data=None, bytes_data=None):
        if text_data:
            try:
                msg = json.loads(text_data)
                if msg.get("type") == "resize":
                    self._writer.channel.change_terminal_size(msg["cols"], msg["rows"])
                    return
            except json.JSONDecodeError, KeyError:
                pass
            self._writer.write(text_data)
        elif bytes_data:
            self._writer.write(bytes_data.decode())

    async def disconnect(self, code):
        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._read_task

        if self._ssh_stack:
            with contextlib.suppress(Exception):
                await self._ssh_stack.__aexit__(None, None, None)

        user = self.scope.get("user")
        if user and user.is_authenticated and hasattr(self, "host_id"):
            await _log_action(
                user,
                self.host_id,
                CustomLogEntry.Action.DISCONNECT,
            )


@database_sync_to_async
def _get_batch_executions(batch_id):
    return list(
        SnippetExecution.objects.filter(batch_id=batch_id).values(
            "id",
            "status",
            "output",
            "exit_code",
        )
    )


@database_sync_to_async
def _get_pending_ids(batch_id):
    return list(
        SnippetExecution.objects.filter(
            batch_id=batch_id, status=SnippetExecution.Status.PENDING
        ).values_list("id", flat=True)
    )


class SnippetExecutionConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        if not self.scope["user"].is_authenticated:
            await self.close()
            return

        self.batch_id = self.scope["url_route"]["kwargs"]["batch_id"]
        self._groups = []
        await self.accept()

        executions = await _get_batch_executions(self.batch_id)
        if not executions:
            await self.send(text_data=json.dumps({"error": "Batch not found"}))
            await self.close()
            return

        # Subscribe to all execution groups
        for ex in executions:
            group_name = f"snippet_exec_{ex['id']}"
            await self.channel_layer.group_add(group_name, self.channel_name)
            self._groups.append(group_name)

        # Send current state
        await self.send(
            text_data=json.dumps(
                {
                    "type": "init",
                    "executions": executions,
                }
            )
        )

        # Start pending executions
        pending_ids = await _get_pending_ids(self.batch_id)
        for exec_id in pending_ids:
            asyncio.create_task(execute_snippet(exec_id))

    async def execution_output(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "type": "output",
                    "execution_id": event["execution_id"],
                    "data": event["data"],
                    "stream": event["stream"],
                }
            )
        )

    async def execution_status(self, event):
        msg = {
            "type": "status",
            "execution_id": event["execution_id"],
            "status": event["status"],
        }
        if "exit_code" in event:
            msg["exit_code"] = event["exit_code"]
        await self.send(text_data=json.dumps(msg))

    async def disconnect(self, code):
        for group_name in self._groups:
            await self.channel_layer.group_discard(group_name, self.channel_name)

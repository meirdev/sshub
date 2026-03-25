import asyncio
import contextlib
import logging

from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from django.utils import timezone

from .models import SnippetExecution
from .ssh import get_host_route, open_ssh_connection

logger = logging.getLogger(__name__)


@database_sync_to_async
def _get_execution(execution_id: int) -> dict:
    ex = SnippetExecution.objects.select_related("snippet", "host").get(pk=execution_id)
    return {
        "id": ex.pk,
        "script": ex.snippet.script,
        "host_id": ex.host_id,
    }


@database_sync_to_async
def _update_status(execution_id: int, status: str, **kwargs):
    SnippetExecution.objects.filter(pk=execution_id).update(status=status, **kwargs)


@database_sync_to_async
def _append_output(execution_id: int, text: str):
    from django.db.models import Value
    from django.db.models.functions import Concat

    SnippetExecution.objects.filter(pk=execution_id).update(
        output=Concat("output", Value(text))
    )


async def execute_snippet(execution_id: int):
    """Run a snippet on a host via SSH, streaming output to channel layer."""
    channel_layer = get_channel_layer()
    group_name = f"snippet_exec_{execution_id}"

    try:
        ex = await _get_execution(execution_id)
    except SnippetExecution.DoesNotExist:
        logger.error("SnippetExecution %s not found", execution_id)
        return

    await _update_status(
        execution_id, SnippetExecution.Status.RUNNING, started_at=timezone.now()
    )
    await channel_layer.group_send(
        group_name,
        {
            "type": "execution.status",
            "execution_id": execution_id,
            "status": SnippetExecution.Status.RUNNING,
        },
    )

    ssh_stack = None
    try:
        route = await get_host_route(ex["host_id"])
        ssh_stack, connection = await open_ssh_connection(route)

        # Upload script to a temp file and execute it
        remote_path = f"/tmp/.snippet_{execution_id}.sh"
        async with connection.start_sftp_client() as sftp:
            async with sftp.open(remote_path, "w") as f:
                await f.write(ex["script"].replace("\r\n", "\n"))
            await sftp.chmod(remote_path, 0o700)

        result = await connection.create_process(
            f"{remote_path} ; _ec=$?; rm -f {remote_path}; exit $_ec",
            term_type="xterm-256color",
        )

        output_buffer = ""
        last_flush = asyncio.get_event_loop().time()

        async def read_stream(stream, stream_name):
            nonlocal output_buffer, last_flush
            try:
                while not stream.at_eof():
                    data = await stream.read(4096)
                    if not data:
                        continue
                    text = (
                        data if isinstance(data, str) else data.decode(errors="replace")
                    )

                    output_buffer += text

                    await channel_layer.group_send(
                        group_name,
                        {
                            "type": "execution.output",
                            "execution_id": execution_id,
                            "data": text,
                            "stream": stream_name,
                        },
                    )

                    now = asyncio.get_event_loop().time()
                    if now - last_flush >= 1.0 or len(output_buffer) >= 4096:
                        await _append_output(execution_id, output_buffer)
                        output_buffer = ""
                        last_flush = now
            except asyncio.CancelledError, OSError:
                pass

        await asyncio.gather(
            read_stream(result.stdout, "stdout"),
            read_stream(result.stderr, "stderr"),
        )

        await result.wait()
        exit_code = result.exit_status

        # Flush remaining buffer
        if output_buffer:
            await _append_output(execution_id, output_buffer)

        status = (
            SnippetExecution.Status.SUCCESS
            if exit_code == 0
            else SnippetExecution.Status.FAILED
        )
        await _update_status(
            execution_id,
            status,
            exit_code=exit_code,
            finished_at=timezone.now(),
        )
        await channel_layer.group_send(
            group_name,
            {
                "type": "execution.status",
                "execution_id": execution_id,
                "status": status,
                "exit_code": exit_code,
            },
        )

    except Exception as e:
        logger.exception("Snippet execution %s failed", execution_id)
        error_msg = f"\n--- Error: {e} ---\n"
        if output_buffer:
            error_msg = output_buffer + error_msg
        await _append_output(execution_id, error_msg)
        await _update_status(
            execution_id,
            SnippetExecution.Status.FAILED,
            finished_at=timezone.now(),
        )
        await channel_layer.group_send(
            group_name,
            {
                "type": "execution.output",
                "execution_id": execution_id,
                "data": error_msg,
                "stream": "stderr",
            },
        )
        await channel_layer.group_send(
            group_name,
            {
                "type": "execution.status",
                "execution_id": execution_id,
                "status": SnippetExecution.Status.FAILED,
            },
        )
    finally:
        if ssh_stack:
            with contextlib.suppress(Exception):
                await ssh_stack.__aexit__(None, None, None)

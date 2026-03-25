import asyncio
import contextlib
import sys

from django.core.management.base import BaseCommand

from core.models import Host
from core.ssh import get_host_route_sync, open_ssh_connection


class Command(BaseCommand):
    help = "Run a command on a host via SSH"

    def add_arguments(self, parser):
        parser.add_argument("host", type=str, help="Host name or ID")
        parser.add_argument("command", type=str, help="Command to run")

    def handle(self, *args, **options):
        host_query = options["host"]
        command = options["command"]

        try:
            host = Host.objects.get(pk=int(host_query))
        except ValueError, Host.DoesNotExist:
            try:
                host = Host.objects.get(name__iexact=host_query)
            except Host.DoesNotExist:
                self.stderr.write(self.style.ERROR(f"Host not found: {host_query}"))
                sys.exit(1)

        route = get_host_route_sync(host.pk)
        exit_code = asyncio.run(self._run(route, command))
        sys.exit(exit_code)

    async def _run(self, route, command):
        stack, connection = await open_ssh_connection(route)
        try:
            result = await connection.run(command)
            if result.stdout:
                self.stdout.write(result.stdout, ending="")
            if result.stderr:
                self.stderr.write(result.stderr, ending="")
            return result.exit_status or 0
        finally:
            with contextlib.suppress(Exception):
                await stack.__aexit__(None, None, None)

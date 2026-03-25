import contextlib

import asyncssh
from channels.db import database_sync_to_async

from .models import Host


def get_host_route_sync(host_id: int) -> list[dict]:
    """Load host and its proxy_jump chain, returning dicts with connection info."""
    host = Host.objects.select_related("proxy_jump").get(pk=host_id)

    result = []
    for h in host.route:
        client_keys = []
        for ck in h.client_keys.all():
            client_keys.append(
                {"public_key": ck.public_key, "passphrase": ck.passphrase or None}
            )
        result.append(
            {
                "host": h.host,
                "port": h.port,
                "username": h.username or None,
                "password": h.password or None,
                "client_keys": client_keys,
            }
        )
    return result


get_host_route = database_sync_to_async(get_host_route_sync)


def build_connect_kwargs(host_info: dict) -> dict:
    """Build asyncssh.connect kwargs from a host info dict."""
    kwargs = {
        "host": host_info["host"],
        "port": host_info["port"],
        "known_hosts": None,
    }
    if host_info["username"]:
        kwargs["username"] = host_info["username"]
    if host_info["password"]:
        kwargs["password"] = host_info["password"]
    if host_info["client_keys"]:
        keys = []
        for ck in host_info["client_keys"]:
            key = asyncssh.import_private_key(ck["public_key"], ck["passphrase"])
            keys.append(key)
        kwargs["client_keys"] = keys
    return kwargs


async def open_ssh_connection(
    route: list[dict],
) -> tuple[contextlib.AsyncExitStack, asyncssh.SSHClientConnection]:
    """Open an SSH connection following the proxy_jump route.

    Returns (stack, connection). Caller must close the stack when done.
    """
    stack = contextlib.AsyncExitStack()
    await stack.__aenter__()

    connection = None
    connect_fn = asyncssh.connect
    for host_info in route:
        kwargs = build_connect_kwargs(host_info)
        connection = await stack.enter_async_context(connect_fn(**kwargs))
        connect_fn = connection.connect_ssh

    assert connection is not None, "Empty route"
    return stack, connection

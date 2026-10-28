"""The sandbox gateway: the only way out of a sandbox network, and the only way in to a preview (ADR 0020).

Runs in its own container, without the Docker socket. The runner attaches it to every session network (alias
`egress`); it is also on the compose network, so it can reach the internet and publish preview ports.

- **Egress proxy** (`:3128`): an HTTP proxy that only allows hosts in `egress.allow` (suffix match). HTTPS goes
  through `CONNECT`; the TLS stays end to end. A host that resolves to a private, loopback, link-local or reserved
  address is refused, so sandboxed code can't reach Codewright's own services or the LAN through it.
- **Preview forwarder**: ports `previews.first_port …` (published on the host's 127.0.0.1 only) are forwarded to the
  preview containers listed in the runner's `routes.json`, read for every new connection.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
import logging
import os
import socket
from pathlib import Path

from codewright_sandbox.config import SandboxConfig

log = logging.getLogger("codewright_sandbox.gateway")

PROXY_PORT = 3128
HEADER_LIMIT = 16_384


def host_allowed(host: str, allow: list[str]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == a or host.endswith("." + a) for a in (x.lower() for x in allow))


def public_address(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return addr.is_global and not addr.is_multicast


async def resolve_public(host: str, port: int) -> list[str]:
    """The public addresses of `host`, IPv4 first; refuses names that resolve to anything private (DNS rebinding).
    Containers usually have no IPv6 route, so trying IPv6 first would stall every download until it timed out."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(str(info[4][0]) for info in sorted(infos, key=lambda i: i[0] != socket.AF_INET)))
    if not addresses or not all(public_address(a) for a in addresses):
        raise PermissionError(f"{host} resolves to a non-public address")
    return addresses


async def connect_any(addresses: list[str], port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    error: Exception = OSError("no address")
    for address in addresses[:4]:
        try:
            return await asyncio.wait_for(asyncio.open_connection(address, port), 8)
        except (OSError, TimeoutError) as e:
            error = e
    raise error


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        with contextlib.suppress(Exception):
            writer.close()


async def splice(
    a: tuple[asyncio.StreamReader, asyncio.StreamWriter], b: tuple[asyncio.StreamReader, asyncio.StreamWriter]
) -> None:
    await asyncio.gather(pipe(a[0], b[1]), pipe(b[0], a[1]))


class Gateway:
    def __init__(self, config: SandboxConfig, state_dir: Path) -> None:
        self.allow = config.egress.allow
        self.previews = range(config.previews.first_port, config.previews.first_port + config.previews.count)
        self.routes_file = state_dir / "routes.json"

    # egress
    async def handle_proxy(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:  # noqa: PLR0911
        peer = writer.get_extra_info("peername")
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 30)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
            writer.close()
            return
        if len(head) > HEADER_LIMIT:
            await self._refuse(writer, 431, "headers too large")
            return
        request_line, *header_lines = head.decode("latin-1").split("\r\n")
        try:
            method, target, version = request_line.split(" ")
        except ValueError:
            await self._refuse(writer, 400, "bad request")
            return
        if method == "CONNECT":
            host, _, port_s = target.rpartition(":")
            port = int(port_s) if port_s.isdigit() else 443
            rest = b""
        else:
            # plain HTTP through a proxy: the target is an absolute URL
            if not target.startswith("http://"):
                await self._refuse(writer, 400, "only absolute http:// URLs or CONNECT")
                return
            authority, _, path = target[len("http://") :].partition("/")
            host, _, port_s = authority.partition(":")
            port = int(port_s) if port_s.isdigit() else 80
            kept = [h for h in header_lines if h and not h.lower().startswith(("proxy-", "connection:"))]
            rest = ("\r\n".join([f"{method} /{path} {version}", *kept, "Connection: close", "", ""])).encode("latin-1")
        host = host.strip("[]")
        if not host_allowed(host, self.allow):
            log.info("refused %s → %s:%s (not in the allowlist)", peer, host, port)
            await self._refuse(writer, 403, f"{host} isn't an allowed package registry")
            return
        if port not in (80, 443):
            await self._refuse(writer, 403, "only ports 80 and 443")
            return
        try:
            upstream = await connect_any(await resolve_public(host, port), port)
        except PermissionError as e:
            await self._refuse(writer, 403, str(e))
            return
        except (OSError, TimeoutError) as e:
            await self._refuse(writer, 502, f"can't reach {host}: {e}")
            return
        if method == "CONNECT":
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
        else:
            upstream[1].write(rest)
            await upstream[1].drain()
        await splice((reader, writer), upstream)

    async def _refuse(self, writer: asyncio.StreamWriter, status: int, reason: str) -> None:
        body = f"Codewright sandbox: {reason}\n".encode()
        writer.write(
            f"HTTP/1.1 {status} Refused\r\nContent-Type: text/plain\r\nContent-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n".encode()
            + body
        )
        with contextlib.suppress(ConnectionError):
            await writer.drain()
        writer.close()

    # previews
    def route(self, port: int) -> tuple[str, int] | None:
        try:
            routes: dict[str, str] = json.loads(self.routes_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        target = routes.get(str(port))
        if not target:
            return None
        host, _, p = target.rpartition(":")
        return host, int(p)

    def preview_handler(self, port: int):  # type: ignore[no-untyped-def]
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            target = self.route(port)
            if target is None:
                body = b"No preview is running on this port.\n"
                writer.write(
                    b"HTTP/1.1 502 No preview\r\nContent-Type: text/plain\r\nContent-Length: "
                    + str(len(body)).encode()
                    + b"\r\nConnection: close\r\n\r\n"
                    + body
                )
                with contextlib.suppress(ConnectionError):
                    await writer.drain()
                writer.close()
                return
            try:
                upstream = await asyncio.wait_for(asyncio.open_connection(*target), 10)
            except (OSError, TimeoutError):
                body = b"The preview isn't answering yet (still starting?). Reload in a moment.\n"
                writer.write(
                    b"HTTP/1.1 503 Starting\r\nContent-Type: text/plain\r\nRetry-After: 2\r\nContent-Length: "
                    + str(len(body)).encode()
                    + b"\r\nConnection: close\r\n\r\n"
                    + body
                )
                with contextlib.suppress(ConnectionError):
                    await writer.drain()
                writer.close()
                return
            await splice((reader, writer), upstream)

        return handle

    async def serve(self) -> None:
        servers = [await asyncio.start_server(self.handle_proxy, "0.0.0.0", PROXY_PORT, limit=HEADER_LIMIT)]
        for port in self.previews:
            servers.append(await asyncio.start_server(self.preview_handler(port), "0.0.0.0", port))
        log.info("egress proxy on :%d, previews on :%d-%d", PROXY_PORT, self.previews[0], self.previews[-1])
        await asyncio.gather(*(s.serve_forever() for s in servers))


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "info").upper(), format="%(asctime)s %(message)s")
    config = SandboxConfig.load(Path(os.environ.get("SANDBOX_CONFIG", "/app/config/sandbox.yaml")))
    asyncio.run(Gateway(config, Path(os.environ.get("STATE_DIR", "/state"))).serve())


if __name__ == "__main__":
    main()

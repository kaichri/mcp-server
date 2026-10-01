"""Two separate MCP applications sharing one tool registry and business logic."""
import asyncio
from contextlib import contextmanager
import logging
import secrets
import signal
from urllib.parse import urlsplit

import jwt
import uvicorn
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from oauth_config import OAuthConfig
from oauth_server import OAuthService


class ProtocolCompatibility:
    """Preserve the existing mcp_dart protocol-header compatibility on LAN only."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope = dict(scope)
            scope["headers"] = [
                (key, b"2025-11-25" if key == b"mcp-protocol-version"
                 and value.decode("latin-1") > "2025-11-25" else value)
                for key, value in scope["headers"]]
        await self.app(scope, receive, send)


class ExternalAuthorization:
    def __init__(self, app, oauth):
        self.app, self.oauth = app, oauth

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not (scope["path"] == "/mcp" or scope["path"].startswith("/mcp/")):
            return await self.app(scope, receive, send)
        auth_headers = [value.decode("latin-1") for key, value in scope["headers"] if key == b"authorization"]
        valid, insufficient, error = False, False, None
        if len(auth_headers) == 1:
            parts = auth_headers[0].split()
            if len(parts) == 2 and parts[0].lower() == "bearer" and len(parts[1]) <= 8192:
                token = parts[1]
                # Explicit legacy compatibility, only when a nonempty secret is configured.
                legacy = self.oauth.config.legacy_token
                if legacy and secrets.compare_digest(token.encode(), legacy.encode()):
                    valid = True
                else:
                    try:
                        claims = self.oauth.verify_access(token)
                        insufficient = "mcp:read" not in claims["scope"].split()
                        valid = not insufficient
                    except (jwt.InvalidTokenError, ValueError, TypeError):
                        error = "invalid_token"
            else:
                error = "invalid_token"
        elif auth_headers:
            error = "invalid_token"
        if not valid:
            if insufficient:
                error = "insufficient_scope"
            challenge = ('Bearer resource_metadata="' + self.oauth.config.public_base_url
                         + '/.well-known/oauth-protected-resource", scope="mcp:read"')
            if error:
                challenge += f', error="{error}"'
            response = JSONResponse({"error": error or "unauthorized"},
                                    status_code=403 if insufficient else 401,
                                    headers={"WWW-Authenticate": challenge, "Cache-Control": "no-store"})
            return await response(scope, receive, send)
        if self.oauth.config.legacy_token and secrets.compare_digest(
                parts[1].encode(), self.oauth.config.legacy_token.encode()):
            # Existing mcp_dart clients also use the legacy token over the Internet.
            scope = dict(scope)
            scope["headers"] = [
                (key, b"2025-11-25" if key == b"mcp-protocol-version"
                 and value.decode("latin-1") > "2025-11-25" else value)
                for key, value in scope["headers"]]
        await self.app(scope, receive, send)


def create_apps(mcp, config):
    oauth = OAuthService(config)
    public = urlsplit(config.public_base_url)
    public_host = public.netloc
    lan_security = TransportSecuritySettings(
        allowed_hosts=[config.lan_host, config.lan_host + ":8000", "localhost:8000", "127.0.0.1:8000"],
        allowed_origins=[f"http://{config.lan_host}:8000"])
    external_security = TransportSecuritySettings(
        allowed_hosts=[public_host, public_host + ":443" if public.port is None else public_host,
                       "localhost:8001", "127.0.0.1:8001", "mcp-server:8001"],
        allowed_origins=[config.public_base_url])
    # Separate session managers: an unauthenticated LAN session cannot cross into the public listener.
    lan = mcp.streamable_http_app(transport_security=lan_security, stateless_http=False, json_response=False)
    external = mcp.streamable_http_app(transport_security=external_security, stateless_http=False, json_response=False)
    lan.add_middleware(ProtocolCompatibility)
    external.router.routes.extend(oauth.routes())
    external.add_middleware(ExternalAuthorization, oauth=oauth)
    return lan, external, oauth


async def serve(mcp):
    config = OAuthConfig.from_env()
    lan, external, oauth = create_apps(mcp, config)
    # Inside Docker bind both interfaces; Compose exposes 8001 exclusively on host loopback.
    class ListenerServer(uvicorn.Server):
        @contextmanager
        def capture_signals(self):
            # One process owns both listeners; do not install competing handlers.
            yield

    servers = [ListenerServer(uvicorn.Config(app, host="0.0.0.0", port=port,
                                           proxy_headers=False, access_log=False, log_level="info",
                                           timeout_graceful_shutdown=15))
               for app, port in ((lan, 8000), (external, 8001))]
    def stop(signum, frame):
        for server in servers:
            if server.should_exit:
                server.force_exit = True
            server.should_exit = True

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    logging.getLogger(__name__).info("LAN MCP :8000; OAuth / legacy bearer MCP :8001")
    tasks = [asyncio.create_task(server.serve()) for server in servers]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for server in servers:
            server.should_exit = True
        await asyncio.gather(*tasks)
        oauth.store.close()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main(mcp):
    asyncio.run(serve(mcp))

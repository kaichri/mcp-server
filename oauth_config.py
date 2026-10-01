"""Validated configuration; public URLs never come from request headers."""
from dataclasses import dataclass
import ipaddress
import os
from pathlib import Path
from urllib.parse import urlsplit


def secret(name: str) -> str:
    filename = os.environ.get(name + "_FILE")
    return Path(filename).read_text(encoding="utf-8").strip() if filename else os.environ.get(name, "")


@dataclass(frozen=True)
class OAuthConfig:
    public_base_url: str
    username: str
    password_hash: str
    database: str = "data/oauth.sqlite3"
    access_seconds: int = 900
    refresh_seconds: int = 2592000
    code_seconds: int = 120
    lan_host: str = "192.168.1.50"
    legacy_token: str = ""

    def __post_init__(self):
        parsed = urlsplit(self.public_base_url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or parsed.path):
            raise ValueError("MCP_PUBLIC_BASE_URL must be an HTTPS origin without a trailing slash")
        hostname = parsed.hostname.lower()
        if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
            raise ValueError("MCP_PUBLIC_BASE_URL must not be a local hostname")
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError("MCP_PUBLIC_BASE_URL must not be a private or loopback address")
        if not self.username or not self.password_hash.startswith("$argon2id$"):
            raise ValueError("Set MCP_OAUTH_USERNAME and an Argon2id MCP_OAUTH_PASSWORD_HASH")
        if not (60 <= self.access_seconds <= 3600 and 60 <= self.refresh_seconds <= 7776000
                and 30 <= self.code_seconds <= 300):
            raise ValueError("Invalid OAuth token lifetime")

    @property
    def resource(self):
        return self.public_base_url + "/mcp"

    @classmethod
    def from_env(cls):
        return cls(
            public_base_url=os.environ.get("MCP_PUBLIC_BASE_URL", "").rstrip("/"),
            username=secret("MCP_OAUTH_USERNAME"),
            password_hash=secret("MCP_OAUTH_PASSWORD_HASH"),
            database=os.environ.get("MCP_OAUTH_DATABASE", "data/oauth.sqlite3"),
            access_seconds=int(os.environ.get("MCP_ACCESS_TOKEN_SECONDS", "900")),
            refresh_seconds=int(os.environ.get("MCP_REFRESH_TOKEN_SECONDS", "2592000")),
            code_seconds=int(os.environ.get("MCP_AUTH_CODE_SECONDS", "120")),
            lan_host=os.environ.get("MCP_LAN_HOST", "192.168.1.50"),
            legacy_token=secret("MCP_AUTH_TOKEN"),
        )

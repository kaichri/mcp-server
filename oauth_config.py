"""Validated configuration; public URLs never come from request headers."""
from dataclasses import dataclass
import base64
import binascii
import ipaddress
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from argon2 import extract_parameters, Type


def validate_password_hash(value: str) -> str:
    """Require a complete, single Argon2id PHC hash with bounded strong parameters."""
    message = "MCP_OAUTH_PASSWORD_HASH must be one complete Argon2id hash (m>=65536, t>=3)"
    match = re.fullmatch(r"\$argon2id\$v=19\$m=\d+,t=\d+,p=\d+\$([A-Za-z0-9+/]+)\$([A-Za-z0-9+/]+)", value)
    if not match:
        raise ValueError(message)
    try:
        params = extract_parameters(value)
        decoded = [base64.b64decode(part + "=" * (-len(part) % 4), validate=True) for part in match.groups()]
    except (ValueError, binascii.Error) as exc:
        raise ValueError(message) from exc
    if (params.type != Type.ID or params.version != 19 or not 65536 <= params.memory_cost <= 262144
            or not 3 <= params.time_cost <= 10 or not 1 <= params.parallelism <= 16
            or len(decoded[0]) < 16 or len(decoded[1]) < 32):
        raise ValueError(message)
    return value


def boolean_env(name: str, default: bool) -> bool:
    value = os.environ.get(name, str(default)).strip().lower()
    if value not in ("true", "false"):
        raise ValueError(name + " must be true or false")
    return value == "true"


def secret(name: str) -> str:
    filename = os.environ.get(name + "_FILE")
    return Path(filename).read_text(encoding="utf-8").strip() if filename else os.environ.get(name, "")


@dataclass(frozen=True)
class OAuthConfig:
    public_base_url: str
    username: str
    password_hash: str
    database: str = "data/oauth.sqlite3"
    access_seconds: int = 3600
    refresh_seconds: int = 63072000
    code_seconds: int = 120
    lan_host: str = "192.168.1.50"
    legacy_token: str = ""
    allow_legacy_token: bool = True

    def __post_init__(self):
        parsed = urlsplit(self.public_base_url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or parsed.path):
            raise ValueError("MCP_PUBLIC_BASE_URL must be an HTTPS origin without a trailing slash")
        if parsed.port is not None and parsed.port != 443:
            raise ValueError("MCP_PUBLIC_BASE_URL must use the public HTTPS port 443")
        hostname = parsed.hostname.lower()
        if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
            raise ValueError("MCP_PUBLIC_BASE_URL must not be a local hostname")
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError("MCP_PUBLIC_BASE_URL must not be a private or loopback address")
        if not self.username or len(self.username) > 200 or any(ord(c) < 32 for c in self.username):
            raise ValueError("Set a valid MCP_OAUTH_USERNAME")
        validate_password_hash(self.password_hash)
        if not self.database or self.database == ":memory:" or self.database.startswith("file:"):
            raise ValueError("MCP_OAUTH_DATABASE must be a persistent SQLite file")
        if not (60 <= self.access_seconds <= 3600 and 60 <= self.refresh_seconds <= 63072000
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
            access_seconds=int(os.environ.get("MCP_ACCESS_TOKEN_SECONDS", "3600")),
            refresh_seconds=int(os.environ.get("MCP_REFRESH_TOKEN_SECONDS", "63072000")),
            code_seconds=int(os.environ.get("MCP_AUTH_CODE_SECONDS", "120")),
            lan_host=os.environ.get("MCP_LAN_HOST", "192.168.1.50"),
            legacy_token=secret("MCP_AUTH_TOKEN"),
            allow_legacy_token=boolean_env("MCP_ALLOW_LEGACY_TOKEN", True),
        )

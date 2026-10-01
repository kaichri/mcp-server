"""Exercise the real server.py process and its two actual HTTP sockets."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

from argon2 import PasswordHasher
import httpx
import pytest


def test_real_two_listener_process(tmp_path):
    # Never interrupt a user's existing server; ASGI tests still run if ports are occupied.
    for port in (8000, 8001):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                pytest.skip(f"Port {port} already in use")
    env = dict(os.environ, MCP_PUBLIC_BASE_URL="https://mcp.example.com",
               MCP_OAUTH_USERNAME="network-test-owner",
               MCP_OAUTH_PASSWORD_HASH=PasswordHasher().hash("network-test-password-only"),
               MCP_OAUTH_DATABASE=str(tmp_path / "oauth.sqlite3"),
               MCP_AUTH_TOKEN="network-test-legacy-only")
    env["MCP_ALLOW_LEGACY_TOKEN"] = "true"
    for name in ["MCP_OAUTH_USERNAME_FILE", "MCP_OAUTH_PASSWORD_HASH_FILE", "MCP_AUTH_TOKEN_FILE"]:
        env.pop(name, None)
    process = subprocess.Popen([sys.executable, "server.py"], env=env,
                               cwd=Path(__file__).resolve().parents[1],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        with httpx.Client(timeout=5, trust_env=False) as client:
            for _ in range(200):
                if process.poll() is not None:
                    stdout, stderr = process.communicate()
                    pytest.fail("Server startup failed: " + stderr.decode(errors="replace"))
                try:
                    response = client.get("http://127.0.0.1:8001/mcp")
                    if response.status_code == 401:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
            else:
                pytest.fail("Both listeners did not become ready")
            body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                               "clientInfo": {"name": "socket-test", "version": "1"}}}
            headers = {"Accept": "application/json, text/event-stream"}
            assert client.post("http://127.0.0.1:8000/mcp", json=body, headers=headers).status_code == 200
            assert client.get("http://127.0.0.1:8000/healthz").json() == {"status": "ok"}
            assert client.get("http://127.0.0.1:8001/healthz").status_code == 404
            assert subprocess.run([sys.executable, "healthcheck.py"], capture_output=True).returncode == 0
            assert client.post("http://127.0.0.1:8001/mcp", json=body, headers=headers).status_code == 401
            assert client.post("http://127.0.0.1:8001/mcp", json=body,
                               headers=dict(headers, Authorization="Bearer network-test-legacy-only")).status_code == 200
            assert client.get("http://127.0.0.1:8001/.well-known/oauth-protected-resource").json()["resource"] == "https://mcp.example.com/mcp"
            assert client.get("http://127.0.0.1:8000/.well-known/oauth-protected-resource").status_code == 404
            assert client.post("http://127.0.0.1:8000/mcp", json=body, headers=headers).status_code == 200
    finally:
        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
        assert b"network-test-legacy-only" not in stdout + stderr
        assert b"network-test-password-only" not in stdout + stderr
        check = subprocess.run([sys.executable, "healthcheck.py"], capture_output=True)
        assert check.returncode == 1 and not check.stdout and not check.stderr

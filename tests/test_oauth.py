import base64
from contextlib import ExitStack
from dataclasses import replace
import hashlib
import json
import re
import time
from urllib.parse import parse_qs, urlsplit

from argon2 import PasswordHasher
import httpx
import jwt
import pytest
from starlette.testclient import TestClient

from listeners import create_apps
from oauth_config import OAuthConfig
from oauth_server import COOKIE, OAuthService
from oauth_store import digest
from server import mcp

BASE = "https://mcp.example.com"
CLIENT = "https://chatgpt.com/oauth/client.json"
REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"
PASSWORD = "test-only-password-with-enough-length"
VERIFIER = "a" * 64
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")
META = {"client_id": CLIENT, "redirect_uris": [REDIRECT],
        "grant_types": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none", "private_key_jwt"],
        "token_endpoint_auth_method": "private_key_jwt"}


@pytest.fixture
def config(tmp_path):
    return OAuthConfig(BASE, "owner", PasswordHasher().hash(PASSWORD),
                       database=str(tmp_path / "oauth.sqlite3"), legacy_token="test-only-legacy-token")


@pytest.fixture
def apps(config):
    lan, external, oauth = create_apps(mcp, config)
    oauth.store.cache_client(CLIENT, META)
    with ExitStack() as stack:
        lan_client = stack.enter_context(TestClient(lan, base_url="http://192.168.1.50:8000"))
        public_client = stack.enter_context(TestClient(external, base_url=BASE))
        yield lan_client, public_client, oauth
    oauth.store.close()


def auth_params(**changes):
    params = {"client_id": CLIENT, "redirect_uri": REDIRECT, "response_type": "code",
              "state": "a-random-client-state", "scope": "mcp:read offline_access", "resource": BASE + "/mcp",
              "code_challenge": CHALLENGE, "code_challenge_method": "S256"}
    params.update(changes)
    return params


def authorize(public, **changes):
    response = public.get("/oauth/authorize", params=auth_params(**changes), follow_redirects=False)
    assert response.status_code == 200, response.text
    fields = dict(re.findall(r'name="(request_id|csrf)" value="([^"]+)"', response.text))
    fields.update(username="owner", password=PASSWORD, decision="allow")
    response = public.post("/oauth/authorize", data=fields, headers={"Origin": BASE}, follow_redirects=False)
    assert response.status_code == 302, response.text
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["state"] == ["a-random-client-state"]
    assert query["iss"] == [BASE]
    return query["code"][0]


def exchange(public, code, **changes):
    data = {"grant_type": "authorization_code", "client_id": CLIENT,
            "code": code, "redirect_uri": REDIRECT, "code_verifier": VERIFIER, "resource": BASE + "/mcp"}
    data.update(changes)
    return public.post("/oauth/token", data=data)


def tokens(public, **changes):
    response = exchange(public, authorize(public, **changes))
    assert response.status_code == 200, response.text
    return response.json()


def rpc_response(response):
    assert response.status_code == 200, response.text
    if response.headers["content-type"].startswith("application/json"):
        return response.json()
    return json.loads(next(line[6:] for line in response.text.splitlines() if line.startswith("data: ")))


def initialize(client, token=None, **headers):
    request_headers = {"Accept": "application/json, text/event-stream", **headers}
    if token:
        request_headers["Authorization"] = "Bearer " + token
    response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                        "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                                                   "clientInfo": {"name": "regression-tests", "version": "1"}}},
                           headers=request_headers)
    return response


def tools_list(client, token=None):
    response = initialize(client, token)
    assert "result" in rpc_response(response)
    headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25",
               "Mcp-Session-Id": response.headers["mcp-session-id"]}
    if token:
        headers["Authorization"] = "Bearer " + token
    assert client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers).status_code == 202
    result = rpc_response(client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=headers))
    return result["result"]["tools"], headers


def test_lan_without_auth_and_external_requires_auth(apps):
    lan, public, _ = apps
    assert "result" in rpc_response(initialize(lan))
    response = initialize(public)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == (
        f'Bearer resource_metadata="{BASE}/.well-known/oauth-protected-resource", scope="mcp:read"')
    assert "result" in rpc_response(initialize(lan))


@pytest.mark.parametrize("token", ["wrong", "test-only-legacy-token"])
def test_legacy_bearer(apps, token):
    _, public, _ = apps
    response = initialize(public, token)
    assert response.status_code == (200 if token == "test-only-legacy-token" else 401)


def test_legacy_disabled_when_empty(config):
    _, app, oauth = create_apps(mcp, replace(config, legacy_token=""))
    with TestClient(app, base_url=BASE) as client:
        assert initialize(client, "test-only-legacy-token").status_code == 401
    oauth.store.close()


@pytest.mark.parametrize("headers", [
    {"Host": "localhost:8001"}, {"Host": "127.0.0.1:8001"},
    {"Host": "192.168.1.50:8000"},
    {"X-Forwarded-For": "127.0.0.1", "X-Real-IP": "192.168.1.2", "X-Forwarded-Host": "localhost"},
])
def test_headers_never_bypass_auth(apps, headers):
    assert initialize(apps[1], **headers).status_code == 401


def test_metadata(apps):
    lan, public, _ = apps
    prm = public.get("/.well-known/oauth-protected-resource").json()
    asm = public.get("/.well-known/oauth-authorization-server").json()
    assert prm["resource"] == BASE + "/mcp"
    assert prm["authorization_servers"] == [BASE]
    assert prm["scopes_supported"] == ["mcp:read", "mcp:write"]
    assert asm["code_challenge_methods_supported"] == ["S256"]
    assert asm["token_endpoint_auth_methods_supported"] == ["none"]
    assert asm["client_id_metadata_document_supported"] is True
    assert asm["authorization_response_iss_parameter_supported"] is True
    assert "offline_access" in asm["scopes_supported"]
    assert "registration_endpoint" not in asm
    assert public.get("/.well-known/oauth-protected-resource/mcp").json() == prm
    assert lan.get("/.well-known/oauth-protected-resource").status_code == 404
    for metadata in [prm, asm]:
        for match in re.findall(r'https?://[^" ]+', json.dumps(metadata)):
            assert match.startswith(BASE)
    assert public.get("/.well-known/oauth-authorization-server", headers={"Host": "evil.invalid", "X-Forwarded-Proto": "http"}).json() == asm


def test_full_oauth_flow_identical_tools_and_call(apps):
    lan, public, _ = apps
    token = tokens(public)["access_token"]
    lan_tools, lan_headers = tools_list(lan)
    public_tools, public_headers = tools_list(public, token)
    assert lan_tools == public_tools
    expected = json.loads(__import__('pathlib').Path("tests/tool_schemas.json").read_text())
    assert {t["name"]: {k: t.get(k) for k in ["inputSchema", "outputSchema"]} for t in lan_tools} == expected
    for tool in lan_tools:
        assert tool["annotations"]["readOnlyHint"] is True
        assert tool["annotations"]["destructiveHint"] is False
        assert tool["annotations"]["idempotentHint"] is True
    for client, headers in [(lan, lan_headers), (public, public_headers)]:
        result = rpc_response(client.post("/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                                       "params": {"name": "current_time", "arguments": {}}}, headers=headers))
        assert "text" in result["result"]["content"][0]
    public_headers.pop("Authorization")
    assert public.post("/mcp", json={"jsonrpc": "2.0", "id": 4, "method": "tools/list"}, headers=public_headers).status_code == 401


@pytest.mark.parametrize("changes", [
    {"code_challenge_method": "plain"}, {"code_challenge_method": ""}, {"code_challenge": ""},
    {"state": ""}, {"resource": "https://other.invalid/mcp"}, {"scope": "admin"},
])
def test_bad_authorization(apps, changes):
    response = apps[1].get("/oauth/authorize", params=auth_params(**changes), follow_redirects=False)
    assert response.status_code in (302, 400)
    if response.status_code == 302:
        query = parse_qs(urlsplit(response.headers["location"]).query)
        assert "error" in query and query["iss"] == [BASE]


def test_bad_redirect_no_open_redirect(apps):
    response = apps[1].get("/oauth/authorize", params=auth_params(redirect_uri="https://evil.invalid/cb"), follow_redirects=False)
    assert response.status_code == 400
    assert "location" not in response.headers


@pytest.mark.parametrize("changes", [
    {"code_verifier": "b" * 64}, {"code_verifier": ""}, {"redirect_uri": REDIRECT + "/wrong"},
    {"resource": "https://other.invalid/mcp"}, {"resource": ""}, {"client_id": "unknown"},
])
def test_bad_exchange(apps, changes):
    public = apps[1]
    response = exchange(public, authorize(public), **changes)
    assert response.status_code in (400, 401)
    assert "access_token" not in response.json()


def test_code_one_use_and_replay_revokes_tokens(apps):
    _, public, _ = apps
    code = authorize(public)
    token = exchange(public, code).json()["access_token"]
    assert exchange(public, code).status_code == 400
    assert initialize(public, token).status_code == 401


def test_code_expiration(apps):
    _, public, oauth = apps
    code = authorize(public)
    oauth.store.execute("UPDATE codes SET expires=0 WHERE hash=?", (digest(code),))
    assert exchange(public, code).status_code == 400


@pytest.mark.parametrize("changes", [
    {"exp": 1}, {"iss": "https://wrong.invalid"}, {"aud": "https://wrong.invalid/mcp"},
])
def test_invalid_jwt_claims(apps, changes):
    _, public, oauth = apps
    token = tokens(public)["access_token"]
    claims = jwt.decode(token, oauth.store.public_key, algorithms=["RS256"], audience=BASE + "/mcp")
    claims.update(changes)
    signed = jwt.encode(claims, oauth.store.private_key, algorithm="RS256")
    response = initialize(public, signed)
    assert response.status_code == 401
    assert 'error="invalid_token"' in response.headers["www-authenticate"]


def test_bad_signature_and_unknown_token(apps):
    _, public, oauth = apps
    token = tokens(public)["access_token"]
    claims = jwt.decode(token, oauth.store.public_key, algorithms=["RS256"], audience=BASE + "/mcp")
    assert initialize(public, jwt.encode(claims, "wrong-test-key-that-is-at-least-32-bytes", algorithm="HS256")).status_code == 401
    claims["jti"] = "unissued"
    assert initialize(public, jwt.encode(claims, oauth.store.private_key, algorithm="RS256")).status_code == 401


def test_missing_scope(apps):
    response = initialize(apps[1], tokens(apps[1], scope="mcp:write")["access_token"])
    assert response.status_code == 403
    assert 'error="insufficient_scope"' in response.headers["www-authenticate"]
    assert 'scope="mcp:read"' in response.headers["www-authenticate"]


def refresh(public, token, **changes):
    form = {"grant_type": "refresh_token", "client_id": CLIENT, "refresh_token": token, "resource": BASE + "/mcp"}
    form.update(changes)
    return public.post("/oauth/token", data=form)


def test_refresh_rotation_replay_and_revocation(apps):
    _, public, _ = apps
    old = tokens(public)
    response = refresh(public, old["refresh_token"])
    assert response.status_code == 200, response.text
    new = response.json()
    assert new["refresh_token"] != old["refresh_token"]
    assert initialize(public, new["access_token"]).status_code == 200
    assert refresh(public, old["refresh_token"]).status_code == 400
    assert refresh(public, new["refresh_token"]).status_code == 400
    assert initialize(public, new["access_token"]).status_code == 401


@pytest.mark.parametrize("changes", [{"resource": "wrong"}, {"scope": "mcp:write"}, {"client_id": "unknown"}])
def test_refresh_rejects_changes(apps, changes):
    public = apps[1]
    old = tokens(public)
    assert refresh(public, old["refresh_token"], **changes).status_code in (400, 401)


def test_refresh_expiry_and_invalid(apps):
    _, public, oauth = apps
    old = tokens(public)
    oauth.store.execute("UPDATE tokens SET refresh_expires=0")
    assert refresh(public, old["refresh_token"]).status_code == 400
    assert refresh(public, "invalid").status_code == 400


@pytest.mark.parametrize("kind", ["access_token", "refresh_token"])
def test_revoke(apps, kind):
    _, public, _ = apps
    old = tokens(public)
    assert public.post("/oauth/revoke", data={"client_id": CLIENT, "token": old[kind]}).status_code == 200
    assert initialize(public, old["access_token"]).status_code == 401
    assert refresh(public, old["refresh_token"]).status_code == 400
    assert initialize(public, "test-only-legacy-token").status_code == 200


def test_no_refresh_without_offline_access(apps):
    assert "refresh_token" not in tokens(apps[1], scope="mcp:read")


def test_csrf_password_and_consent(apps):
    public = apps[1]
    response = public.get("/oauth/authorize", params=auth_params())
    assert "Secure" in response.headers["set-cookie"] and "HttpOnly" in response.headers["set-cookie"]
    fields = dict(re.findall(r'name="(request_id|csrf)" value="([^"]+)"', response.text))
    fields.update(username="owner", password=PASSWORD, decision="allow")
    assert public.post("/oauth/authorize", data=fields, headers={"Origin": "https://evil.invalid"}).status_code == 403
    bad = dict(fields, csrf="wrong")
    assert public.post("/oauth/authorize", data=bad, headers={"Origin": BASE}).status_code == 403
    bad = dict(fields, password="wrong")
    assert public.post("/oauth/authorize", data=bad, headers={"Origin": BASE}).status_code == 403
    assert public.post("/oauth/authorize", data=fields, headers={"Origin": BASE}).status_code == 403


def test_denied_consent(apps):
    public = apps[1]
    response = public.get("/oauth/authorize", params=auth_params())
    fields = dict(re.findall(r'name="(request_id|csrf)" value="([^"]+)"', response.text))
    fields["decision"] = "deny"
    response = public.post("/oauth/authorize", data=fields, headers={"Origin": BASE}, follow_redirects=False)
    assert response.status_code == 302
    params = parse_qs(urlsplit(response.headers["location"]).query)
    assert params["error"] == ["access_denied"] and params["iss"] == [BASE]


def test_persistence_and_credentials_hashed(apps, config):
    _, public, oauth = apps
    old = tokens(public)
    restarted = OAuthService(config)
    assert restarted.verify_access(old["access_token"])["sub"] == "owner"
    assert restarted.query_client(CLIENT).client_id == CLIENT
    row = restarted.store.one("SELECT * FROM tokens")
    assert row["refresh_hash"] == digest(old["refresh_token"])
    assert old["refresh_token"] not in str(dict(row))
    restarted.store.close()


def test_duplicate_parameters_and_wrong_content_type(apps):
    public = apps[1]
    assert public.post("/oauth/token", json={"grant_type": "authorization_code"}).status_code == 400
    assert public.post("/oauth/token", content="client_id=x&client_id=y", headers={"Content-Type": "application/x-www-form-urlencoded"}).status_code == 400
    assert public.get("/oauth/authorize", params=list(auth_params().items()) + [("resource", "wrong")]).status_code == 400


def test_login_rate_limit(apps):
    _, _, oauth = apps
    for _ in range(10):
        assert not oauth.store.limited("login", 10)
    assert oauth.store.limited("login", 10)


def test_cimd_validation_and_ssrf(config, monkeypatch):
    oauth = OAuthService(config)
    real_client = httpx.Client
    requested = []

    def transport(request):
        requested.append(str(request.url))
        return httpx.Response(200, json=META)

    monkeypatch.setattr("oauth_server.httpx.Client", lambda **kwargs: real_client(transport=httpx.MockTransport(transport), **kwargs))
    assert oauth.query_client(CLIENT).client_id == CLIENT
    for client_id in ["http://chatgpt.com/oauth/client.json", "https://127.0.0.1/oauth/client.json",
                      "https://chatgpt.com.evil.invalid/oauth/client.json", "https://chatgpt.com/oauth/client.json?x=1"]:
        assert oauth.query_client(client_id) is None
    assert requested == [CLIENT]
    oauth.store.execute("DELETE FROM clients")
    bad_meta = dict(META, client_id="wrong")
    monkeypatch.setattr("oauth_server.httpx.Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=bad_meta)), **kwargs))
    assert oauth.query_client(CLIENT) is None
    oauth.store.close()


def test_lan_legacy_protocol_compatibility(apps):
    lan = apps[0]
    response = initialize(lan)
    headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2026-07-28",
               "Mcp-Session-Id": response.headers["mcp-session-id"]}
    assert lan.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers).status_code == 202
    assert "result" in rpc_response(lan.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=headers))


def test_external_legacy_protocol_compatibility(apps):
    public = apps[1]
    response = initialize(public, "test-only-legacy-token")
    headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2026-07-28",
               "Mcp-Session-Id": response.headers["mcp-session-id"], "Authorization": "Bearer test-only-legacy-token"}
    assert public.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers).status_code == 202
    assert "result" in rpc_response(public.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=headers))


def test_lan_session_not_accepted_on_external(apps):
    lan, public, _ = apps
    token = tokens(public)["access_token"]
    response = initialize(lan)
    headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25",
               "Mcp-Session-Id": response.headers["mcp-session-id"], "Authorization": "Bearer " + token}
    assert public.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=headers).status_code == 404


@pytest.mark.parametrize("method", ["GET", "DELETE", "OPTIONS", "POST"])
def test_every_external_method_requires_header(apps, method):
    response = apps[1].request(method, "/mcp?access_token=test-only-legacy-token")
    assert response.status_code == 401


def test_parallel_code_exchange(apps):
    from concurrent.futures import ThreadPoolExecutor
    public = apps[1]
    code = authorize(public)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: exchange(public, code), range(2)))
    assert sorted(r.status_code for r in results) == [200, 400]


def test_parallel_refresh_replay_revokes_family(apps):
    from concurrent.futures import ThreadPoolExecutor
    public = apps[1]
    old = tokens(public)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: refresh(public, old["refresh_token"]), range(2)))
    assert sorted(r.status_code for r in results) == [200, 400]
    new = next(r.json() for r in results if r.status_code == 200)
    assert initialize(public, new["access_token"]).status_code == 401


@pytest.mark.parametrize("base", ["http://mcp.example.com", "https://localhost", "https://127.0.0.1",
                                  "https://192.168.1.50", "https://example.local", "https://example.org/mcp",
                                  "https://user:pass@example.org", "https://example.org?x=1"])
def test_reject_bad_public_base(config, base):
    with pytest.raises(ValueError):
        replace(config, public_base_url=base)


@pytest.mark.parametrize("changes", [
    {"redirect_uris": ["https://evil.invalid/cb"]}, {"redirect_uris": [REDIRECT + "*"]},
    {"redirect_uris": ["http://chatgpt.com/cb"]}, {"redirect_uris": []},
    {"token_endpoint_auth_methods_supported": ["private_key_jwt"]}, {"grant_types": None},
])
def test_reject_bad_cimd(config, monkeypatch, changes):
    oauth = OAuthService(config)
    real_client = httpx.Client
    metadata = dict(META, **changes)
    monkeypatch.setattr("oauth_server.httpx.Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=metadata)), **kwargs))
    assert oauth.query_client(CLIENT) is None
    oauth.store.close()


@pytest.mark.parametrize("status", [302, 404])
def test_cimd_no_redirects_or_error_fallback(config, monkeypatch, status):
    oauth = OAuthService(config)
    real_client = httpx.Client
    calls = []
    def response(req):
        calls.append(str(req.url))
        return httpx.Response(status, headers={"Location": "http://127.0.0.1/secret"}, json=META)
    monkeypatch.setattr("oauth_server.httpx.Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(response), **kwargs))
    assert oauth.query_client(CLIENT) is None
    assert calls == [CLIENT]
    oauth.store.close()

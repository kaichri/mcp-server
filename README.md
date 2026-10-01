# Synology MCP Server

A Python MCP server for Exa web search and page retrieval, finance news, current time, and YouTube metadata, transcripts, and comments. Two separate HTTP listeners share the same tool registry, schemas, and business logic.

| Access | Endpoint | Authentication |
| --- | --- | --- |
| Trusted LAN | `http://<NAS_LAN_IP>:8000/mcp` | None |
| ChatGPT / Internet | `https://mcp.example.com/mcp` | OAuth 2.1, Authorization Code + PKCE S256 |
| Existing Internet clients | The same public endpoint | `Authorization: Bearer <MCP_AUTH_TOKEN>` remains supported |

Authentication depends exclusively on the listener. `Host`, client IP, `X-Forwarded-For`, `X-Real-IP`, and `X-Forwarded-Host` never bypass external authentication. Host and origin checks also protect the MCP transport but do not select authentication. Proxy headers are not used to generate public URLs.

## Setup and venv

Use Python 3.13. A virtual environment isolates local dependencies and is never committed.

Windows PowerShell:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
```

Linux / macOS:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

`requirements.txt` is sufficient for runtime use; `requirements-dev.txt` adds pytest. Run `deactivate` to leave the environment. Recreate it and install dependencies on another computer. Direct dependencies are pinned to tested versions; pip resolves transitive dependencies.

## Configure OAuth

**Keep** your existing `.env` and `MCP_AUTH_TOKEN`. Add the settings from `config.env.example`. All addresses below are placeholders: replace the public origin and `<NAS_LAN_IP>` with your actual deployment values in the ignored local `.env` only.

```dotenv
MCP_PUBLIC_BASE_URL=https://mcp.example.com
MCP_LAN_BIND_IP=<NAS_LAN_IP>
MCP_OAUTH_USERNAME=owner
MCP_ALLOW_LEGACY_TOKEN=true
MCP_ACCESS_TOKEN_SECONDS=900
MCP_REFRESH_TOKEN_SECONDS=2592000
MCP_AUTH_CODE_SECONDS=120
```

Choose a long, private login password. Generate its Argon2id hash interactively:

```bash
python oauth_admin.py hash-password
```

Save the output as the only line in `secrets/oauth-password-hash.txt`. Alternatively, create and check the file directly:

```bash
python oauth_admin.py hash-password --output secrets/oauth-password-hash.txt
python oauth_admin.py verify-password --hash-file secrets/oauth-password-hash.txt
```

Both commands prompt for the password interactively. `--output` writes exactly one hash followed by a newline, without displaying it or overwriting an existing file. `verify-password` reports only success or failure. Without `--hash-file`, it uses the configured hash secret or `secrets/oauth-password-hash.txt`.

The file and directory are excluded from Git and the Docker build context. Docker Compose mounts the file as a secret at `/run/secrets/oauth_password_hash`. Keep plaintext passwords and real tokens out of project files and shell commands. Configuration accepts only a complete Argon2id hash with strong, bounded parameters; extra file contents and weak hashes prevent startup. The generator uses 64 MiB of memory, three iterations, four parallel lanes, a 16-byte salt, and a 32-byte hash.

After transferring the file to the NAS, set permissions for the container user from the project directory over SSH:

```bash
sudo chown 10001:10001 secrets/oauth-password-hash.txt
sudo chmod 600 secrets/oauth-password-hash.txt
```

Additional DSM ACLs must allow UID 10001 to read the file. File-backed Compose secrets may inherit bind-mount permissions; do not assume that `uid`, `gid`, or `mode` is applied automatically. After startup, verify readability without displaying the hash:

```bash
docker compose exec mcp-server python -c "from pathlib import Path; from oauth_config import validate_password_hash; validate_password_hash(Path('/run/secrets/oauth_password_hash').read_text().strip()); print('Secret is readable and valid')"
docker compose exec mcp-server python oauth_admin.py verify-password
```

There is one private user. The username and password hash come from configuration or secrets; no additional user management is needed. Missing OAuth configuration prevents startup so that the external listener cannot accidentally run without protection.

| Variable | Meaning / default |
| --- | --- |
| `MCP_PUBLIC_BASE_URL` | Public HTTPS origin; required for direct Python startup |
| `MCP_OAUTH_USERNAME` | Private login username; required |
| `MCP_OAUTH_PASSWORD_HASH_FILE` | Argon2id hash file; configured by Compose |
| `MCP_OAUTH_PASSWORD_HASH` | Alternative to the hash file for direct startup |
| `MCP_AUTH_TOKEN` | Existing static bearer token; retain it for existing clients |
| `MCP_ALLOW_LEGACY_TOKEN` | `true` (default) or `false`; disables legacy access without deleting the token |
| `MCP_AUTH_TOKEN_FILE` | Alternative secret file for direct startup |
| `MCP_OAUTH_USERNAME_FILE` | Alternative secret file for the username |
| `MCP_OAUTH_DATABASE` | Docker: `/data/oauth.sqlite3`; local: `data/oauth.sqlite3` |
| `MCP_LAN_BIND_IP` | Compose bind IP for port 8000; set your NAS LAN IP (generic default `192.168.1.50`) |
| `MCP_LAN_HOST` | Allowed LAN host for direct startup; set your NAS LAN IP (generic default `192.168.1.50`) |
| `MCP_ACCESS_TOKEN_SECONDS` | Access-token lifetime; default 900 seconds / 15 minutes |
| `MCP_REFRESH_TOKEN_SECONDS` | Absolute refresh-family lifetime; default 2592000 seconds / 30 days |
| `MCP_AUTH_CODE_SECONDS` | One-time code lifetime; default 120 seconds |

`*_FILE` takes precedence over the corresponding direct secret value. The static token has no automatic expiration; revoke it by changing or removing configuration and restarting. An empty token or `MCP_ALLOW_LEGACY_TOKEN=false` disables this access path. After migration, prefer OAuth and set the legacy switch to `false`. It affects only `/mcp` on the external listener, never login, token, or discovery endpoints. Port 8000 remains unauthenticated independently.

Direct Python startup does **not** automatically load `.env`. PowerShell example after creating the secret file:

```powershell
$env:MCP_PUBLIC_BASE_URL = "https://mcp.example.com"
$env:MCP_OAUTH_USERNAME = "owner"
$env:MCP_OAUTH_PASSWORD_HASH_FILE = "$PWD\secrets\oauth-password-hash.txt"
$env:MCP_LAN_HOST = "<NAS_LAN_IP>"
python server.py
```

Also provide `MCP_AUTH_TOKEN` in the process environment for existing Internet clients. Direct Python operation binds both ports to `0.0.0.0`; the firewall must restrict port 8001 to the local reverse proxy. Use the Docker deployment below for the NAS.

## Docker

```bash
docker compose config --quiet
docker compose up -d --build
```

`docker compose config --quiet` validates without displaying environment values. The normal detailed configuration output can disclose secrets.

Port mappings:

- `<NAS_LAN_IP>:8000:8000`: unauthenticated LAN access on the NAS LAN address.
- `127.0.0.1:8001:8001`: authenticated backend port on NAS loopback for the reverse proxy.

Both listeners bind to `0.0.0.0` inside the container. Do not use host networking, which would remove the port-mapping restrictions. The container runs without root privileges as UID/GID 10001. Ensure that existing `/data` volumes are writable by this user.

The named `oauth-data` volume stores SQLite, the RSA signing key, client metadata, authorization codes, refresh-token hashes, token families, and revocations. Normal restarts and rebuilds preserve these records. `docker compose down -v` deletes the volume and all OAuth connections. Protect backups of the volume and login secret; back up a live SQLite database with its backup API or after a clean shutdown. Signing keys and databases are sensitive runtime data and must not be committed.

The Docker healthcheck checks LAN `/healthz` (database available) and external `/mcp` (401 with a bearer challenge) every 30 seconds. It uses no token or login and prints no sensitive data. `/healthz` exists only on port 8000; it does not bypass `/mcp` authentication. The healthcheck marks the container healthy or unhealthy; `restart: unless-stopped` alone does not restart a merely unhealthy container.

```bash
docker inspect --format '{{.State.Health.Status}}' synology-mcp
docker compose exec mcp-server python healthcheck.py
```

## Synology Reverse Proxy

DSM 7: **Control Panel > Login Portal > Advanced > Reverse Proxy**. Configure your public hostname; `mcp.example.com` is an example:

| Field | Source / external | Destination / internal |
| --- | --- | --- |
| Protocol | HTTPS | HTTP |
| Hostname | `mcp.example.com` | `127.0.0.1` |
| Port | `443` | `8001` |
| Path / forwarding | Entire origin `/` | Preserve paths unchanged |

DSM versions without a separate path field route by hostname and port; do not restrict forwarding to `/mcp`. `/oauth/*` and `/.well-known/*` must also reach port 8001. Remove or update conflicting rules. Assign a valid TLS certificate for your public hostname; use HSTS if the domain is exclusively HTTPS.

The public rule must **no longer target port 8000**. LAN clients continue using `http://<NAS_LAN_IP>:8000/mcp`. OAuth does not require a second public domain.

Forward `Authorization`, `Accept`, `Content-Type`, `Mcp-Session-Id`, and `MCP-Protocol-Version` unchanged. Preserve the public `Host`; the backend also accepts `127.0.0.1:8001` / `localhost:8001`. Do not rewrite Location headers. Synology WebSocket presets are unnecessary for Streamable HTTP / SSE. Use sufficient HTTP/SSE read timeouts and disable SSE response buffering if available. Do not log Authorization headers, OAuth query strings, or form bodies in reverse-proxy / DSM logs; authorization codes appear in the browser callback. Uvicorn access logs are therefore disabled.

## Firewall

- Internet: expose only TCP 443 to the NAS.
- Do not forward router ports 8000 or 8001.
- Do not create a public reverse-proxy rule targeting unauthenticated port 8000.
- LAN: allow port 8000 only from trusted LAN subnets; restrict guest and VPN networks.
- Port 8001: NAS loopback / reverse proxy only; never expose it directly to LAN or Internet clients.

Check port bindings and DSM/router rules after deployment from a separate network. Docker port publication may interact with firewall rules differently from regular host processes; retain loopback and LAN-IP bindings.

Check the installed Docker Engine version on the NAS:

```bash
docker version --format '{{.Server.Version}}'
docker port synology-mcp
```

Port 8000 must bind to your NAS LAN IP and port 8001 to `127.0.0.1`, never `0.0.0.0` or `[::]`. Container Manager can change port settings when recreating a container; check after GUI changes. With Docker Engine **before 28.0.0**, other machines on the same Layer 2 network can reach localhost-published ports in some configurations. This is a documented [Docker limitation](https://docs.docker.com/engine/network/port-publishing/), independent of OAuth. Test port 8001 from a second LAN computer; if reachable, use a supported Engine version or additional effective network/firewall rules. The port still requires authentication.

## OAuth endpoints and security behavior

| Endpoint | Purpose |
| --- | --- |
| `GET /.well-known/oauth-protected-resource` | Protected Resource Metadata |
| `GET /.well-known/oauth-protected-resource/mcp` | Equivalent path-specific metadata |
| `GET /.well-known/oauth-authorization-server` | Authorization Server Metadata |
| `GET /oauth/authorize` | Validation, login, and explicit consent |
| `POST /oauth/authorize` | CSRF-protected login and consent |
| `POST /oauth/token` | Authorization code / refresh token |
| `POST /oauth/revoke` | Revoke the token family for this client |

Example issuer: `https://mcp.example.com`. The resource and JWT audience consistently use **`https://mcp.example.com/mcp`**, the concrete MCP endpoint. Metadata URLs come exclusively from `MCP_PUBLIC_BASE_URL`, never request or proxy headers.

Authlib 1.8 processes authorization-code and refresh grants and PKCE. PyJWT/cryptography sign access tokens with RS256 and verify signature, issuer, audience, and expiration; database checks also enforce issuance, revocation, and stored permissions. The persistent RSA key is generated on first startup. Opaque refresh tokens and codes are stored only as SHA-256 hashes. Authorization codes are short-lived and single-use; SQLite serializes concurrent token transactions.

Refresh tokens are issued with `offline_access` and compatible client metadata. Each refresh rotates the token. The absolute family lifetime does not extend; log in again after 30 days. Reusing an old refresh token revokes the whole family, including access tokens. Reusing a code also revokes its issued tokens. `/oauth/revoke` revokes the corresponding family. Legacy static-token access is independent.

All seven existing tools require `mcp:read`: `current_time`, `web_search`, `web_fetch`, `finance_news_candidates`, `youtube_metadata`, `youtube_transcript`, and `youtube_comments`. Annotations are `readOnlyHint=true`, `destructiveHint=false`, and `idempotentHint=true`. `mcp:write` is reserved; there are currently no write/delete tools. A token with only `mcp:write` cannot access the read tools. `offline_access` is an authorization-server scope, not a required resource scope.

External tool descriptors declare `securitySchemes=[{"type":"oauth2","scopes":["mcp:read"]}]`; LAN descriptors declare `[{"type":"noauth"}]`. Both also contain `_meta["securitySchemes"]`. Installed Python SDK 2.2.0 has no matching decorator parameter and discards unknown fields in its `Tool` model. Its public context-middleware API returns `tools/list` as a wire dictionary, allowing these extensions without SDK patches or tool-schema changes. The listener marker comes from the server-side ASGI scope, never headers. [OpenAI documents the declaration and compatibility field](https://developers.openai.com/plugins/reference).

Login uses Argon2id, secure HttpOnly/SameSite cookies, CSRF binding to a five-minute single-use request, and explicit consent. There are no persistent browser logins. Global persistent rate limits allow 10 login attempts per minute, 60 authorization-page requests, and 120 token and revocation requests each. A failed login requires restarting OAuth. Limits do not rely on client-IP headers.

Missing or invalid tokens receive external HTTP 401 with:

```http
WWW-Authenticate: Bearer resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource", scope="mcp:read"
```

Invalid tokens add `error="invalid_token"`. Valid OAuth tokens without `mcp:read` receive 403 with `error="insufficient_scope"`. A valid configured static token can access all existing tools. Tokens in query strings are rejected and are never forwarded to Exa or YouTube.

For rejected identifiable `tools/call` requests, the same HTTP 401/403 response also includes an MCP tool error (`isError=true`) with `_meta["mcp/www_authenticate"]`, including resource-metadata URL, scope, error, and description. The HTTP challenge remains authoritative for transport clients; no anonymous tool executes and no second login flow starts. JSON request reading is bounded; malformed or large requests retain the HTTP authentication error. This follows [OpenAI tool-auth documentation](https://developers.openai.com/plugins/build/auth); verify actual ChatGPT UI behavior during the NAS connection test.

Login, OAuth error, and discovery responses include `no-store`, `no-cache`, `no-referrer`, `nosniff`, `X-Frame-Options: DENY`, restrictive CSP, and disabled camera/microphone/geolocation permissions. COOP is not added to avoid interfering with popup/redirect communication.

SQLite uses WAL and a 5000 ms busy timeout. Code redemption, refresh rotation, and replay revocation remain atomic. Cleanup runs on new authorization requests; there are no new background services. Database, WAL, and SHM files have Linux mode 0600. There are no foreign-key relationships. New RSA keys have 3072 bits; persistent existing keys require at least 2048 bits. No JWKS endpoint is needed because the same resource server validates its issued tokens locally.

Existing mcp_dart protocol-header compatibility remains for LAN and legacy Internet token clients. OAuth clients use normal MCP protocol negotiation. The listeners have separate MCP sessions.

## Connect ChatGPT

Select your public MCP URL, represented here as `https://mcp.example.com/mcp`, with OAuth in ChatGPT's MCP/app dialog. Prefer CIMD; no manually entered client secret is needed. The server advertises `client_id_metadata_document_supported=true` and `token_endpoint_auth_methods_supported=["none"]`. It reads the current ChatGPT metadata document and chooses the supported intersection `none`; the singular legacy preference `private_key_jwt` does not prevent this compatible choice.

This private server permits CIMD URLs only at `https://chatgpt.com/oauth/client.json` or `https://chatgpt.com/oauth/<callback_id>/client.json`. Allowed redirects are `https://chatgpt.com/connector_platform_oauth_redirect` and `https://chatgpt.com/connector/oauth/<callback_id>`, additionally matched **exactly** against published client metadata. No other hosts/paths, wildcards, credentials, fragments, or query strings are allowed. HTTPS fetching has a timeout, a 64-KiB size limit, exact JSON content-type validation, `trust_env=False`, and no redirect following. The server provides no DCR, OIDC, or `private_key_jwt` endpoints. ChatGPT also supports DCR/static clients, but the selected CIMD configuration does not require them.

Expected flow:

1. ChatGPT requests `/mcp` without a token and receives 401 with discovery information.
2. ChatGPT reads Protected Resource Metadata and Authorization Server Metadata.
3. ChatGPT identifies itself through CIMD, currently `https://chatgpt.com/oauth/client.json`.
4. ChatGPT starts Authorization Code + PKCE S256 with `state` and resource `/mcp`.
5. Enter the username/password in the browser and allow access.
6. The server redirects to the exact callback with a one-time code, unchanged `state`, and `iss`.
7. ChatGPT exchanges the code/verifier for an access token and, with `offline_access`, a refresh token.
8. ChatGPT calls `/mcp` with its bearer token and renews access using the refresh token.

Published issuer metadata currently enables the stable callback `https://chatgpt.com/connector_platform_oauth_redirect`. The actual client metadata document is authoritative. LAN clients and existing static Internet token clients remain usable in parallel.

## curl tests

The server uses **Streamable HTTP with sessions and SSE**. A plain GET to `/mcp` without an MCP session is not a complete functional test and may return a transport error. Use POST `initialize` instead. These examples use Bash; on Windows use `curl.exe` and appropriate shell quoting. Replace `<NAS_LAN_IP>` and the example public hostname before running requests.

LAN without authentication: expect HTTP 200 and an MCP initialize response (SSE):

```bash
curl -i --max-time 10 'http://<NAS_LAN_IP>:8000/mcp' \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"curl-test","version":"1"}}}'
```

Internet without authentication: expect HTTP 401 and `WWW-Authenticate`:

```bash
curl -i https://mcp.example.com/mcp
```

Discovery: expect HTTP 200 and public HTTPS URLs only:

```bash
curl -i https://mcp.example.com/.well-known/oauth-protected-resource
curl -i https://mcp.example.com/.well-known/oauth-authorization-server
```

Internet with an OAuth access token **or an existing static token**: expect HTTP 200 and an initialize response:

```bash
curl -i --max-time 10 https://mcp.example.com/mcp \
  -H 'Authorization: Bearer <TOKEN>' \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"curl-test","version":"1"}}}'
```

For subsequent MCP calls, send the returned `Mcp-Session-Id` and `MCP-Protocol-Version: 2025-11-25`, and first send `notifications/initialized`. Tests automate this flow, including `tools/list` and `tools/call`.

## Tests and revocation

```bash
python -m pytest -q
```

Tests run both ASGI apps with their actual MCP lifecycle and cover the full login/token flow, legacy clients, manipulated headers, metadata, PKCE, single-use codes, JWT claims, scopes, refresh rotation/expiration, revocation, CSRF, persistence, and CIMD validation. A schema baseline from the previous server protects existing tool names and input/output schemas. Real network smoke tests check both HTTP listeners independently.

Hardening tests add listener-specific security metadata under concurrent requests, MCP authentication challenges, the legacy switch, complete password hashes and admin verification, startup failure before listeners open, healthcheck, SQLite key/rate-limit persistence, and official callback formats.

Administratively revoke all OAuth families:

```bash
docker compose exec mcp-server python oauth_admin.py revoke-all
```

This does not change the static `MCP_AUTH_TOKEN`. Disable it with `MCP_ALLOW_LEGACY_TOKEN=false` and recreate the container; for permanent revocation also change or remove the token.

## Final setup checklist

### One-time setup

1. Install Python dependencies, run `python oauth_admin.py hash-password`, and save only its hash to `secrets/oauth-password-hash.txt`. Alternatively use `hash-password --output secrets/oauth-password-hash.txt`. Check it with `verify-password`.
2. Transfer the file to the NAS and set the permissions for UID 10001 described above. Keep and extend your existing ignored `.env`; replace the example values with your own deployment settings:

```dotenv
MCP_PUBLIC_BASE_URL=https://mcp.example.com
MCP_LAN_BIND_IP=<NAS_LAN_IP>
MCP_OAUTH_USERNAME=owner
MCP_ALLOW_LEGACY_TOKEN=true
```

Initially retain the existing `MCP_AUTH_TOKEN`. Then run from the NAS project directory:

```bash
docker compose config --quiet
docker compose up -d --build
```

3. Route the entire public HTTPS origin on port 443 to `http://127.0.0.1:8001` through Synology Reverse Proxy.
4. Check port mappings, secret readability, healthcheck, and firewall. LAN remains at `http://<NAS_LAN_IP>:8000/mcp` without authentication.

### After deployment

```bash
curl -i --max-time 10 'http://<NAS_LAN_IP>:8000/mcp'
curl -i https://mcp.example.com/mcp
curl -sS https://mcp.example.com/.well-known/oauth-protected-resource
curl -sS https://mcp.example.com/.well-known/oauth-protected-resource/mcp
curl -sS https://mcp.example.com/.well-known/oauth-authorization-server
```

A plain LAN GET must not return an authentication challenge but may return an MCP session/Accept transport error. For a positive functional test, use the `initialize` POST above and expect HTTP 200. An external GET without a token must return 401. All discovery documents must advertise public HTTPS URLs and resource `/mcp`. Port 8001 must be inaccessible from another LAN computer. Then complete a real ChatGPT connection, login, and tool call; disable the legacy switch afterwards if desired.

## LAN

MCP URL: `http://<NAS_LAN_IP>:8000/mcp`
Authentication: **None**. Trusted local networks only.

## ChatGPT / Internet

MCP URL: `https://mcp.example.com/mcp`
Authentication: **OAuth 2.1**, plus the existing static bearer token for legacy clients.
Public Base URL: `https://mcp.example.com`
Protected Resource Metadata: `https://mcp.example.com/.well-known/oauth-protected-resource`
OAuth Metadata: `https://mcp.example.com/.well-known/oauth-authorization-server`

## Specifications and deployment limits

Sources checked on October 1, 2026:

- [MCP Authorization Specification 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)
- [MCP Client Registration / CIMD](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/client-registration)
- [OpenAI MCP OAuth / CIMD and ChatGPT](https://developers.openai.com/plugins/build/auth)
- [Authlib Authorization Server](https://docs.authlib.org/en/latest/oauth2/authorization_server.html)

Local automated tests do not replace checking NAS router, firewall, and DSM configuration. Change the reverse-proxy target to 8001 and rebuild the container on the NAS. Then run LAN and Internet requests from their respective networks and complete the actual browser login in ChatGPT. Repository changes alone do not update a running NAS container. Keep all real deployment settings in ignored local files; committed documentation and test addresses are generic examples.

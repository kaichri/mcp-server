# Exa providers: implementation and verification

Verified on 2026-10-02. Local changes only; no commit, push or NAS deployment.

## Current schemas and sources

Primary sources:

- [Exa OpenAPI JSON](https://exa.ai/docs/exa-spec.json)
- [Search](https://exa.ai/docs/reference/search)
- [Contents](https://exa.ai/docs/reference/get-contents)
- [Deep Search](https://exa.ai/docs/search/deep-search)
- [Error codes](https://exa.ai/docs/admin/error-codes)
- [Remote MCP](https://exa.ai/docs/get-started/exa-mcp)

The official OpenAPI was fetched and its referenced request schemas resolved.
The live Remote MCP `list_tools` was checked independently, without sending a key.

| Operation | Verified request | Response |
| --- | --- | --- |
| Direct Search | `POST https://api.exa.ai/search`, `x-api-key`; required `query`, optional `objective`, `numResults`, `type`, `contents` | Ranked `results`, optional `requestId`, `costDollars`, synthesis `output` |
| Direct Contents | `POST https://api.exa.ai/contents`, `x-api-key`; either `urls` or `ids`, 1–100 entries; `text.maxCharacters` supported | `results` and optional per-URL `statuses`; a 200 response can contain failed URLs |
| Direct Deep | Same `/search`, `type="deep"`; `outputSchema={"type":"text",...}` requests grounded synthesis | `results`, optional `output.content` and `output.grounding` |
| Remote Search | `web_search_exa`, required `query` **and** `objective`; optional `numResults` | Text/Markdown or structured JSON represented as text |
| Remote Contents | `web_fetch_exa`, required `urls:string[]`; optional `maxCharacters` | Markdown title/URL blocks, one per page |

`objective` expresses the task goal beyond the query. Our compatibility wrappers
use a fixed instruction to prioritize original relevant sources, exclude noise
and duplicates, and extract supporting evidence. This is not a duplicate query.
Direct receives the same instruction even though its schema does not require it.

Normal search uses `auto` plus bounded highlights, not Deep or synthesis. Explicit
Deep selects five results and asks for a concise grounded text output. We also
checked the opt-in Remote `web_search_advanced_exa` schema: its advertised `type`
enum is only `auto`, `fast`, `instant`. Therefore no Remote Deep mode is assumed.

## Provider routing and limits

`exa_provider.py` defines the provider protocol, Direct and Remote adapters,
structured results, classified errors and an in-process shared Direct breaker.
A future SearXNG provider can implement that protocol; none is installed.

| Mode | Search / Contents |
| --- | --- |
| `auto`, key present | Direct first; Remote for authentication, quota, rate-limit, timeout or availability failures |
| `auto`, key absent | Remote directly |
| `direct` | Direct only, including missing-key errors; no Remote/HTTP fallback |
| `remote_mcp` | Remote only; Direct key never forwarded |

Deep is Direct-only because no matching Remote capability was verified. It
returns the actual Direct error, or `remote_deep_not_supported` without a usable
Direct selection. It is never triggered by normal search or search-and-fetch.

Fetch fallback is Direct → Remote → an optional injected `HTTPReader`. No generic
local HTTP implementation is enabled: the existing extractor is an experimental
PoC, and production must not import its browser code. The interface documents
public-DNS pinning, redirect validation and bounded I/O requirements for a future
reader. Without that reader, Remote failure returns a structured error with
safe provider attempts. Remote has its own limits and is not guaranteed free.

The original `web_search` and `web_fetch` string contracts and input schemas are
preserved. Remote success text remains text; Direct results render compatible
Title/URL/Published labels. Finance-news discovery now uses the corrected search
wrapper as well. Original authentication and X tools remain intact. Both new
tools receive the existing listener-specific OAuth / LAN security metadata.

`web_search_and_fetch` keeps source rank order, deduplicates URLs, fetches at most
five in one request, then distributes the remaining text budget across pages.
Limits: 20 results, 20,000 characters per page, 50,000 combined text characters,
2 MiB per upstream response, 25 seconds per ordinary provider call, 65 seconds
for Deep, 90 seconds for the combined workflow. Search snippets are capped at
1,000 characters in the combined response. Partial results are mapped by source
URL/ID; only failed eligible URLs are sent to fallback, never successful pages.
Unmapped Remote batch text is not attributed to an unrelated URL.

## Errors, breaker and secrets

| Category | Basis / action |
| --- | --- |
| `EXA_AUTH_ERROR` | 401/403 authentication/feature failure or missing key; `configuration_error=true`; auto may fall back |
| `EXA_QUOTA_EXHAUSTED` | Documented `NO_MORE_CREDITS`, `API_KEY_BUDGET_EXCEEDED`, `TEAM_BUDGET_EXCEEDED`, or billing status 402 |
| `EXA_RATE_LIMITED` | 429 or documented rate tag |
| `EXA_TIMEOUT` | Network/request timeout, 408/504 |
| `EXA_UNAVAILABLE` | Network failure, 5xx, overloaded tag, malformed/oversized response |
| `EXA_INVALID_REQUEST` | Invalid local input, documented invalid-request tags, 400/404/409/422; no fallback |
| `EXA_UNKNOWN_ERROR` | Unclassified error; no speculative retry |

Documented content-policy rejections are invalid requests and are not bypassed.
Target-page `CRAWL_HTTP_403` and similar crawl failures are separate from API-key
403 and do not open the account circuit. Documented quota tags take precedence
over status, so classification does not depend solely on an assumed HTTP code.
Remote exceptions, including SDK exception groups, are reduced to safe categories.

Quota cooldown defaults to 3,600 seconds; rate cooldown to 60 seconds. Configure
both through `EXA_QUOTA_COOLDOWN_SECONDS` / `EXA_RATE_LIMIT_COOLDOWN_SECONDS`
(1–2,592,000 seconds). Search and Contents share the breaker for the same key in
the current process. Already-open checks do not extend cooldown. A key change
selects a separate circuit. There is no invented monthly reset, persistent
cross-process state, automatic retry loop or assumed remaining credit balance.

The Direct key comes only from environment variables, is hidden in configuration
repr, is sent only as a header to the fixed HTTPS API origin, and is never sent
to Remote. Redirects and environment HTTP proxies are disabled for Direct. Raw
upstream error bodies and exceptions are not returned or logged. Known key echoes
in successful provider responses are redacted. Response metadata is bounded.
Keep the Exa key in ignored `config.env`. Compose uses the service's `env_file`;
local Python commands inherit it after dot-sourcing `tools/load-config-env.ps1`
in the same PowerShell session. Existing MCP/OAuth `.env` settings remain separate.

## Usage and completeness

Responses retain provider name, requested/canonical URL, title, author,
publication date and retrieval time. `complete=null`, `completeness="unknown"`
reflect that extraction alone cannot prove full source coverage. Local truncation
is marked separately. Retrieval time does not claim the source was freshly crawled.

Returned `costDollars` is stored under `usage.estimated_cost_dollars` with
`billing_exact=false`, not as exact usage, billing or available balance. Missing
usage stays null; Remote supplies no verified billing metadata. No guessed local
billing counter or credit reset is introduced.

## Live checks and tests

During the initial implementation phase, no Direct API live calls were made: `EXA_API_KEY` was absent in the process and
in the project's ignored `.env`. Consequently Direct auth, live response timing,
quality and Deep usage are **not yet verified against the account**. Direct
tests use HTTPX mock transport and a plainly synthetic key, with no credit use.

Live Remote checks succeeded for both default tool schemas and the opt-in
advanced schema. One batch Contents call for `https://example.org` and
`https://example.com`, 500 characters per page, succeeded with two mapped text
blocks and no usage data. This verifies Remote batch parsing, not Direct API auth.

For the next Direct live smoke after local key configuration, make only one
search for `Qwen 3.8 Flash Next`, one returned-URL read, one two-URL batch, and one
small explicit Deep request. Record wall time, source quality and provider-supplied
usage without logging the key. A local key must not be sent through chat.

Automated verification covers schemas/objective, single/batch Contents, Deep,
source ordering and bounds, all error categories, Direct/Remote selection,
eligible fallbacks, HTTP extension, partial URL failures, breaker expiry and key
changes, missing keys, response/error key leakage, original contracts, OAuth
metadata and unchanged business functions. The completed full run passed
**269 tests in 27.14 seconds**:
all prior 201 checks plus 68 new Exa checks. `git diff --check` passed. `.env`,
virtual environments, bytecode caches, logs and local databases remain ignored.
`docker compose --env-file config.env.example config --quiet` also passed with
synthetic authentication data and a documentation-only LAN address; no container
was started. The focused source scan found no obvious literal credentials.

Subsequent account-backed live verification completed successfully: Direct
Search, single Contents, two-URL batch Contents, Deep and Auto all returned
Direct results without fallback. The recovery run used exactly three additional
requests and no retries. See [the live protocol](exa-direct-live-smoke.json).
The final regression passed 269 tests in 27.17 seconds; Compose, diff and exact-key
checks passed. Productive code was unchanged. Recommendation: **READY_TO_COMMIT**.

## Browser decision and next step

**DO_NOT_INTEGRATE_BROWSER** for general Web tools. The prior PoC found sufficient
Exa extraction, approximately 1 GiB browser RAM, and no demonstrated general-page
content benefit. X remains a separate possible future enhancement. No production
browser package or dependency was added.

Recommended next step: configure the key locally and run the four bounded Direct
smoke checks before considering deployment. No NAS settings were touched here.

# Public X integration: live smoke report

Date: 2026-10-02. Local Windows execution, anonymous HTTP only. No X account, account cookies, authentication, paid service, browser automation or NAS deployment was used. Nothing was committed or pushed.

## Decision

**Further correction is necessary before committing/deploying this as the requested full-post, thread and search integration.** The current provider is useful for best-effort public previews and metadata. Green offline tests do not establish live feature coverage.

The main diagnostic matrix contained 23 scenarios and 20 provider fetch calls, run sequentially with the provider's request spacing. Preliminary probes inspected four posts, four queries, one public HTML page and one search challenge. There was no repeated retry loop or captcha bypass. The matrix returned 11 `ok:true` responses and 12 structured failures; several successful responses were deliberately partial, not successful completion of the requested feature.

## Live post scenarios

| Scenario / public source | Actual result after the correction |
| --- | --- |
| [Short text and quote-bearing Qwen post](https://x.com/Alibaba_Qwen/status/1955068429679149162) | 67-character main preview, author Qwen, username and UTC timestamp. Quote content/identity were not discovered; reported unknown rather than absent. |
| [Qwen post containing a URL](https://x.com/Alibaba_Qwen/status/1886105723047973138) | 298-character preview, one text URL, author Qwen, UTC timestamp and a public preview image. The longer post was not fully retrieved. |
| [NVIDIA mention post](https://x.com/NVIDIA_AI_PC/status/2039740487490515007) | 162-character preview and `GoogleGemma` mention. Public `og:url` identifies the current username `NVIDIARTXSpark`; canonical URL and name now use that identity. |
| [Alibaba hashtag/media post](https://x.com/AlibabaGroup/status/1926909626508869999) | 233-character preview, `Qwen`, `AlibabaAI`, `SmartGlasses`, `CustomerExperience`, author/time and a preview image. Full video metadata was not obtained. |
| [DGX Spark thread starting post](https://x.com/kchonyc/status/1978156587320803734) | 300-character preview and `nvidia` mention. The indexed public source describes a six-post thread, but the provider did not establish the complete thread relationship. |

Post IDs and normalized URLs are retained. Author names and timestamps are taken from current public SEO metadata, not invented or inferred from search snippets. Full text, expanded URLs, quote content, conversation IDs and media attachments could not all be independently verified. All these live results remain `complete:false`, `completeness:"partial"`, `metadata_complete:false`.

`image_preview` means the page's public preview image. It can represent a quote or summary rather than a verified attachment to the main post. It is explicitly marked `page_preview_not_verified_post_attachment`. `quote_status:"unknown"` prevents a null quote field from falsely asserting that the post has no quote.

## Threads

The DGX Spark thread was tested with `max_posts=3`, with both values of `include_replies`, and with `max_posts=1`.

- The starting post is present and deduplicated.
- Only one connected post was returned. Same-author continuation posts were not established.
- Public page links led to readable candidates, but missing reply/conversation metadata meant they could not safely be claimed as part of the thread.
- Discovery was blocked. The three-post runs report `posts_found:1`, `complete:false`, `termination_reason:"blocked"`. The one-post run reports `max_posts_reached`.
- Chronological sorting and foreign-reply exclusion cannot be meaningfully demonstrated by a single live post; these remain covered by offline relationship fixtures.

**`x_read_thread` is not practically sufficient for resolving complete public threads with this provider.** No result claims a confirmed thread end.

## Search and user search

The actual provider was tested with `Qwen`, `DGX Spark`, `RTX 5090` and `FreeToken`, each with `limit=2`. A Qwen date range (`2025-01-01` inclusive to `2026-01-01` exclusive) and user search for `Alibaba_Qwen` / `Qwen` were also tested. The user-search provider invocation is the same path used by `x_search_user`.

Every live search was stopped by DuckDuckGo's HTTP 202 HTML anti-bot challenge. It is now classified as `BLOCKED`; no challenge was solved and no internal X search was attempted. Consequently:

- There are no verified live search results from `x_search` or `x_search_user`.
- Relevant public posts were found independently to select smoke-test targets; that research is **not** counted as success of the implemented discovery provider.
- Live author/date filtering, relevance, result-count limits and deduplication after discovery could not be validated end to end. Offline fixtures cover these behaviors.

**Neither search tool has demonstrated usable live results from this environment.** Changing the user agent or introducing cookies to bypass the challenge was not attempted.

## Cache

The successful public Qwen URL post was tested against a separate ignored local SQLite file:

| Step | Provider fetches | `cached` | Fetch time |
| --- | ---: | --- | --- |
| Initial `refresh=true` read | 1 | false | New UTC timestamp |
| Repeated normal read | 0 | true | Unchanged |
| `refresh=true` | 1 | false | New UTC timestamp |

The result identifies `provider:"public_http"`, `cached`, `fetched_at` and the partial completeness status. Twitter aliases and tracking parameters used the same cached post ID with zero additional fetches. Cached previews remain previews; caching does not increase completeness.

## Error and URL cases

- Nonexistent status ID: structured `NOT_FOUND`. This is an unavailable-post test, not proof of a separately identified deleted post.
- `twitter.com` alias and query/tracking parameters: canonical X URL and cache reuse succeed.
- A public `t.co` link redirects to a non-X destination: rejected as `UNSUPPORTED_URL`, rather than expanding the allowlist.
- Invalid X path, non-X URL, localhost URL and LAN-IP URL: rejected locally with zero provider fetches.
- No raw transport exceptions were returned in the live matrix.
- A verified deleted post and protected-account live case were not separately exercised. Protected/deleted parsing and DNS/redirect SSRF cases remain covered offline.

## Minimal changes and verification

Changes following live observations:

1. Parse public `og:title`, matching `og:url`, `article:published_time` and `og:image` metadata. Correct account renames only when the post ID matches.
2. Treat DuckDuckGo HTTP 202 as a blocked challenge.
3. Add post `complete`, explicit quote uncertainty, preview-image attribution and unavailable completeness on structured errors.
4. Add thread `posts_found`, `completeness` and machine-readable `termination_reason`; keep `complete:false`.
5. Add search provider/fetch-time/completeness/count metadata.

A minimal synthetic fixture reproduces the real SEO structure without copying entire post bodies or page scripts: `tests/fixtures/x_public_live_meta.html`. Four additional regression tests cover metadata extraction, identity/rename handling and HTTP-202 classification. Existing thread tests now check termination metadata. The normal suite remains fully offline.

Final result: **176 passed** (all prior 172 tests plus four new regression tests). Whitespace checks pass. NAS, Git history and the remote repository are unchanged.

## Next step

Do not deploy this as a reliable complete reader/search integration yet. The actual public HTML delivers truncated SEO previews rather than the full post graph; it does not establish quote/reply relationships. A browser fallback is worth evaluating for full text, but anonymous rendering may still encounter login gates and would not itself fix blocked search discovery. No Playwright dependency was added.

First identify and validate an anonymous, publicly supported source for fuller post data and a genuinely usable free discovery source. Any later fallback must preserve destination checks, bounded requests and the prohibition on login/cookies/captcha bypass. Thread completeness must remain unconfirmed until an end can actually be established.

# Free public X sources: evaluation

Evaluated on 2026-10-02 from the local development machine. All probes used anonymous public GET requests, no account, credentials or cookie jar. Response sizes and deadlines were bounded; no captcha, consent, robots restriction or authentication requirement was bypassed. No provider was added, no dependency installed, and no NAS/Git remote operation performed.

## Result

**No validated free combination currently meets the requested discovery + full-post + public-thread requirements from this environment. Further correction/evaluation is necessary before deployment.** The existing SEO reader remains useful for explicitly partial previews. Public availability in a browser or an independent research search engine is not evidence that our HTTP provider can reproduce those results.

## Provider matrix

`Unknown` means the capability could not be evaluated because the preflight/access path failed. It does not assert that the source never supports that feature elsewhere.

| Tested source | Discovery / user search | Full single post | Threads | Quote / media / timestamp | Login and cost in these probes | Block, stability and limits |
| --- | --- | --- | --- | --- | --- | --- |
| Existing X SEO HTML | No discovery | Only previews verified | Only seed established | Quote unknown; preview images; precise public timestamp | No login, free | Reachable; incomplete; current parser limits apply |
| DuckDuckGo HTML (previous live phase) | Blocked | Not a content reader | Not a content reader | Not applicable | Anonymous, free | HTTP 202 anti-bot challenge; not retried or bypassed |
| Bing HTML | No valid status URLs for Qwen | Not a content reader | Not a content reader | Not applicable | Anonymous, free | HTTP 200, ten result blocks; decoded result wrappers lead to general Qwen sites |
| Bing RSS | Zero status URLs across all four requested queries | Not a content reader | Not a content reader | Not applicable | Anonymous, free | HTTP 200 XML, ten items/query, poor site/keyword compliance; no suitability demonstrated |
| Google HTML | Unknown | Not a content reader | Not a content reader | Not applicable | Consent needed before tested results; no login attempted | HTTP 302 to `consent.google.com`; stopped there |
| Brave HTML | Unknown | Not a content reader | Not a content reader | Not applicable | Anonymous free page attempted; no paid API | HTTP 429; no retry after rate limiting |
| Yahoo HTML | No results obtained | Not a content reader | Not a content reader | Not applicable | Anonymous, free | Bounded GET probes encountered repeated HTTP 307 redirects; no usable results |
| Mojeek HTML | Blocked | Not a content reader | Not a content reader | Not applicable | Anonymous, free | HTTP 200 page titled `Captcha`; no bypass |
| X oEmbed | No discovery | Readable short text; long example still truncated | No thread graph | Text links; no structured quote/media/conversation fields; date footer only | No login/key, free in tests | Four tested posts reachable; usefulness limited to embeds/previews; rate limits not stress-tested |
| Public CDN syndication `tweet-result` | No discovery | Not demonstrated | Not demonstrated | None extracted | Anonymous request, no token acquisition | HTTP 200 with `{}`; no private API or authentication workarounds attempted |
| Official embed HTML | No discovery | Initial document contains no post content | Not demonstrated | None in initial document | Anonymous, free | HTTP 200, 429-byte JavaScript application shell; rendering not executed |
| `nitter.net` | Unknown | Unknown | Unknown | Unknown | No login attempted | Connection refused; no further content requests |
| `nitter.poast.org` | Unknown | Unknown | Unknown | Unknown | No login attempted | DNS resolution failed; no further content requests |
| `xcancel.com` | Unknown | Unknown | Unknown | Unknown | No login attempted | `robots.txt` HTTP 451; no further content requests |
| `nitter.privacyredirect.com` | Unknown | Unknown | Unknown | Unknown | No login attempted | Robots preflight redirects to another site, `privacyredirect.com`; not treated as a working Nitter instance |
| `nitter.tiekoetter.com` | Not tested after robots restriction | Not tested | Not tested | Not tested | No login attempted | Robots HTTP 200 explicitly disallows the tested post, timeline and search paths; restrictions respected |

No source's long-term stability, freshness or rate-limit capacity has been established by these small probes. No requests were sent to blocked Nitter content paths and no random instance was integrated into runtime code. The instance candidates came from the project's [public instance list](https://github.com/zedeus/nitter/wiki/Instances); the [project README](https://github.com/zedeus/nitter/blob/master/README.md) also describes its dependence on unofficial upstream access, so a reachable third-party frontend would still require separate reliability evaluation.

## Actual discovery queries and quality

Searches used `site:x.com Qwen`, `site:x.com "DGX Spark"`, `site:x.com "RTX 5090"` and `site:x.com FreeToken`.

All four were run against Bing RSS. Each response contained ten items and **zero normalized X/Twitter status URLs**. Qwen results primarily referenced model websites/docs, DGX Spark results referenced NVIDIA/product pages, RTX 5090 results referenced product/retailer pages, and FreeToken returned unrelated image/resource sites. Neither relevance to exact query nor the site constraint could be relied on. Their freshness was not established. Bing HTML was separately parsed, including its base64-wrapped links, with the same absence of usable Qwen status URLs.

Google and Brave were initially tested with Qwen. Their consent redirect and rate limit prevented result evaluation; the remaining queries were not sent to those blocked sources. Yahoo and Mojeek were also given one Qwen probe each. This avoids turning an access failure into a repeated scraping attempt.

There is therefore no best validated discovery source. `x_search` and `x_search_user` remain practically blocked with the existing discovery provider. A paid API was not considered an eligible replacement.

## Embed and syndication details

Official public oEmbed was tested via `publish.twitter.com/oembed`, using public Twitter-format status URLs and `omit_script=true`. This was an anonymous endpoint read, not X API account access. Public fields were inspected without executing returned HTML or widget scripts.

| Public post type | oEmbed main paragraph length | What was actually available |
| --- | ---: | --- |
| Long [Qwen update](https://x.com/Alibaba_Qwen/status/1886105723047973138) | 301 characters | Author and HTML paragraph; original longer post still not fully exposed |
| Short [Qwen quote-bearing post](https://x.com/Alibaba_Qwen/status/1955068429679149162) | 91 characters | Main text plus a short URL; quote author/body/ID not supplied as structured fields |
| [DGX Spark thread seed](https://x.com/kchonyc/status/1978156587320803734) | 302 characters | Author, mention, short URL and footer; no continuation/conversation graph |
| [Alibaba hashtag/media post](https://x.com/AlibabaGroup/status/1926909626508869999) | 258 characters | Hashtag anchors, short URL and footer; no structured media variants |

Paragraph lengths exclude author/date footer text. An embed link to another post would not itself prove a quote relationship. Missing structured quote fields are not interpreted as proof of no quote. No full thread or verified thread end was returned by any tested embed source.

The CDN `tweet-result` sample returned an empty JSON object, not an HTTP error. No guest/authentication token was acquired and no private GraphQL endpoint was tested. The official `platform.twitter.com/embed/Tweet.html` sample returned an empty application div and script references only. We did not execute or download those scripts.

No embed provider was integrated: this evaluation did not establish a material, dependable improvement sufficient for the requested full reader or thread feature. oEmbed is a possible future source of short-link enrichment, but adding another network fetch per post now would not solve the principal shortcomings.

## Combined approach

The required chain is discovery → supported status URL → existing reader → optional public enrichment. The discovered sources failed at different stages:

- Bing yielded no supported status URL to hand to the reader.
- Google/Brave/Yahoo/Mojeek did not yield a usable search response.
- oEmbed can enrich a hand-selected URL, but supplied neither a reliable full-text improvement for the long sample nor thread data.
- Public syndication returned no data, and Nitter preflights did not establish an eligible working source.

We did not replace failed live discovery with hard-coded URLs, synthetic search results, cached research snippets or fixture data. There is no successful end-to-end live combined search to report. The existing interfaces and SSRF checks remain unchanged.

## Playwright assessment, without installation

The official embed HTML shell demonstrates that a JavaScript-capable browser could render more than the initial document **if its subsequent anonymous requests succeed**. It does not prove that public X threads load without login, that captchas are absent, or that all continuation posts become available. No Playwright/Chromium live run was performed and no such success is claimed.

A separate anonymous browser proof of concept would be required before recommending installation. It would need a fresh nonpersistent context, no account credentials or imported cookies, bounded navigation/scrolling, denied downloads, and enforced public destination checks for subresources, workers, redirects and frames. It must stop at login/captcha gates. A browser must not be used to defeat search-engine rate limits or challenges.

The [official Docker guidance](https://playwright.dev/python/docs/docker) confirms that browsers and OS dependencies are additional components, and recommends a separate user/seccomp configuration for untrusted-page crawling. This would increase this project's small Python container's image size, process count and memory/CPU use. No resource benchmark was performed, and NAS-specific sandbox/architecture compatibility is unverified. It is not appropriate to silently change the working Synology deployment to an unsandboxed browser image.

**Recommendation:** no automatic Playwright dependency or deployment change. The current evidence justifies a separately scoped anonymous rendering experiment, not a claim that Playwright solves full threads or search.

## Repository and tests

This evaluation adds this report and a README link only. No runtime provider, fallback cascade, tool parameter, dependency or security allowlist was changed. Thus no new parser/fetcher regression is introduced in this phase and no new automated test was needed. Diagnostic pages and summaries are stored under ignored `.venv/` paths.

The complete offline suite was run again: **176 tests passed**. All four tool interfaces and the original 106 tests remain covered. No commit, push or NAS change was made.

## Recommendation by requested capability

- **Best discovery:** none validated; search/user search not ready.
- **Best single-post source:** existing SEO reader for honest partial previews. oEmbed is an additional reachable preview source, not a proven full-post replacement.
- **Best thread source:** none validated; the current thread reader remains incomplete and cannot confirm an end.
- **Quote/media improvement:** no tested alternative supplied reliable structured quote/media data beyond the existing preview metadata.
- **Commit/deployment decision:** further correction/evaluation necessary for the advertised full-post/thread/search functionality. Do not present reachability or passing offline tests as proof of productive coverage.

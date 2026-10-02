# Anonymous X Playwright proof of concept

Date: 2026-10-02. Local Windows/Python 3.13. Playwright 1.63.0,
Chromium 153.0.8010.12, psutil 7.2.2. This is a diagnostic experiment,
not a provider integration or a Synology deployment.

## Decision

**PLAYWRIGHT_NOT_WORTH_IT for the current NAS production integration.**

This qualification matters: normal, visible Chromium demonstrated substantial
DOM improvements, including a long post, all six numbered thread posts and a
quote's identity/body. Playwright is therefore technically useful for these
public pages, rather than merely reproducing SEO previews. However, neither
tested headless variant worked, anonymous search produced no results, and the
successful browser used roughly 1.2–1.3 GiB of process-tree working set. A
reliable unattended Linux/container reader has not been demonstrated. Adding
it to the working server now would introduce a heavy, unvalidated dependency.

A paid provider is **not proven necessary** by these results. Likewise, this
experiment does not establish that headless Chromium always fails or that
visible Chromium always succeeds on other machines, IPs or dates.

## Isolation and reproduction

The only executable added is [`tools/x_playwright_probe.py`](../tools/x_playwright_probe.py).
It is not imported by the MCP server and is not part of normal pytest discovery.
The production requirements, Dockerfile, compose configuration, tool interfaces
and provider code were not changed in this phase.

Installation was into `.venv/x-playwright-poc`, with browser binaries in
`.venv/x-playwright-browsers`. Raw public-page observations and measurements are
under `.venv/x-playwright-*.json`. All of these paths are ignored by Git.
No X account, existing browser profile, saved session or account cookies were
used. Each URL receives a fresh, ephemeral browser context. Cookies naturally
created by the site are not exported, recorded or reused between URLs.

The probe does not click, log in, accept cookies, play videos or solve challenges.
Only bounded scrolling and DOM reads are performed. Downloads and service
workers are disabled; WebSockets are closed. Destinations are restricted to
explicit X/Twitter asset hosts, resolved to public addresses before launch and
pinned using Chromium resolver rules. Other destinations are rejected, including
observed Sentry telemetry and `jf.x.com` onboarding requests. Media resource
downloads are blocked in the later matrix; DOM poster/image metadata remains
available. A 1,000-request per-case ceiling is now enforced. These diagnostic
controls are not a security certification for a future browser provider.

No request headers/bodies, Authorization values, cookies, storage, guest tokens,
HAR or trace are written. Document metadata is limited to status, content type,
length and server. Naturally received JSON is examined only for top-level key
names and a whitelist of public tweet fields; no internal operation is built
or replayed. No useful tweet JSON was observed in these runs.

Example, using the already-created isolated environment:

```powershell
.venv\x-playwright-poc\Scripts\python.exe tools\x_playwright_probe.py `
  https://x.com/Alibaba_Qwen/status/1886105723047973138 `
  --headed --scrolls 3 --output .venv/x-playwright-example.json
```

Without `--headed`, Playwright uses its default Chromium headless shell.
`--full-chromium` selects the full Chromium binary in headless mode. Neither
selection spoofs a user agent or uses stealth patches. The full browser exposes
its natural `HeadlessChrome/153.0.0.0` user agent when headless.

## Live comparison matrix

Each successful headed post was compared with a fresh, uncached HTTP reader
call to the exact same input URL. "Complete visible body" describes what the
page rendered, not a guarantee against an authoritative original/archive.

| Scenario / public URL | Existing HTTP reader | Visible Chromium / Playwright | Default headless shell |
| --- | --- | --- | --- |
| [Normal NVIDIA mention post](https://x.com/NVIDIA_AI_PC/status/2039740487490515007) | 162-character body, author/current username, UTC time, mention and one unverified page preview | Same 162-character body, current `NVIDIARTXSpark` identity, status ID/link, displayed timestamp, mention anchor and article-associated image. A same-author follow-up and a foreign reply are also visible. | 403; empty DOM |
| [Long Qwen post](https://x.com/Alibaba_Qwen/status/1886105723047973138) | 298-character truncated preview | 704-character visible body, including the flexible-modes and unlimited-input sections and the closing sentence. Author, username, status link, displayed timestamp, expanded external links and article-associated image are available. | 403; empty DOM |
| [Six-post DGX Spark thread](https://x.com/kchonyc/status/1978156587320803734) | 300-character seed preview; previously only one connected post from `x_read_thread` | Six distinct same-author posts marked `(1/6)` through `(6/6)`, plus one foreign reply. Already present before scrolling. | 403; empty DOM |
| [Qwen quote post](https://x.com/Alibaba_Qwen/status/1955068429679149162) | 67-character main text; quote identity/body unknown | Same 67-character main body plus a nested 245-character quote body, author Tianbao Xie, username `TianbaoX`, ID/link `1954939485881594123`. | 403; empty DOM |
| [Alibaba hashtag/video post](https://x.com/AlibabaGroup/status/1926909626508869999) | 233-character body and page preview; media attribution unverified | 233-character main text (additional article UI is excluded), four hashtag anchors, video element, poster thumbnail and a later browser-local blob URL. No downloadable video variant or nonempty attachment alt-text was established. | 403; empty DOM |
| Public search `Qwen` | Existing discovery previously blocked by DuckDuckGo's challenge | Redirect to `/i/jf/onboarding/web`, cookie-consent UI and "Something went wrong"; zero result articles | 403; empty DOM |
| Public search `DGX Spark` | Existing discovery previously blocked by DuckDuckGo's challenge | Same onboarding/cookie UI; zero result articles | 403; empty DOM |

Full Chromium in headless mode was also tried for the five post URLs and
`DGX Spark` search. Navigation failed before a usable document appeared. A
single diagnostic repeat of the long post identified
`net::ERR_HTTP_RESPONSE_CODE_FAILURE`, with no blocked destination request.
It must not be counted as a successful fetch or silently assigned an HTTP
status that the probe did not receive. No retries or browser masking were added.

## DOM findings, quotes and media

The successful pages contain `article` elements, author/profile anchors,
`[dir="auto"]` text blocks, status links, accessible labels, images and video
elements. **No `data-testid` values, `<time>` nodes, JSON-LD or application/json
script blocks were observed** in the captured successful DOM. The original
test-id selectors therefore returned empty arrays; the probe was expanded to
record generic text blocks and nested article counts. It does not assume older
X DOM conventions still exist.

The main post ID comes from its timestamp/status anchor. Timestamps are visible
localized strings such as `6:33 PM · Feb 2, 2025`; they are not a precise UTC
machine timestamp. The existing SEO reader remains better for UTC metadata.
Mentions, hashtags and external links can be read from actual anchors, without
following their destinations. Author profile images must be distinguished from
post attachments; not every image in an article is media belonging to that post.

The quote card is a nested article inside the Qwen post. It independently
contains `Tianbao Xie`, `@TianbaoX`, public text and a status/date anchor. This is
a much stronger quote association than a bare `t.co` link. The DOM body was
245 characters; it was not independently compared with the quoted original to
prove there are no omitted portions. The quote must not be counted as a reply
or as the main author's thread continuation.

Image URLs include actual `pbs.twimg.com/media/...` attachments, beyond the
HTTP reader's ambiguous page preview. Attachment alt attributes were empty in
the tested main posts; profile-image alt values are not attachment descriptions.
The video post provided a poster and later `blob:https://x.com/...` source.
A blob URL is browser-local and is not a portable media download URL. No video
stream API was constructed, and full formats, duration or codec are unverified.

## Thread result and stopping behavior

The six visible same-author status IDs, in numbered order, are:

1. `1978156587320803734`
2. `1978156590231388304`
3. `1978156591976206360`
4. `1978156596409630933`
5. `1978156599408546262`
6. `1978156603124719748`

Each article identifies `@kchonyc` and the corresponding `(n/6)` marker.
The seventh article is a reply by `@elmanmansimov`, readily separable by its
own author and status link. Three 1,000-pixel scrolls, separated by two seconds,
left article counts at **7 → 7 → 7 → 7**. Other tested pages likewise did not
increase their article counts after scrolling.

This establishes the presence of the author's six declared posts for this
sample, **not a generic conversation graph or a guaranteed thread-end signal**.
No conversation/reply IDs were exposed in machine-readable JSON. The UI may
omit replies or additional continuations, and a lack of new articles after
bounded scrolling is not evidence of completeness. No future implementation
should mark arbitrary threads complete based only on unchanged counts.

## Search, login, challenges and stability

**Public search without login: no usable results in this experiment.** The
headed browser redirected both queries to onboarding and displayed cookie
choices and an error, with zero articles. No cookie-consent choice or login
interaction was made. Because `jf.x.com` was blocked by the explicit destination
policy, the final onboarding error is not attributed exclusively to X's login
policy. The decisive observation is that untouched anonymous search did not
produce results; unrestricted or authenticated search was not tested.

All five distinct headed post pages returned 200, despite fresh contexts.
They included a "Log in or sign up for X" prompt but readable public articles
remained available. No captcha was displayed on those successful pages. The
headless shell returned 403 on all seven initial cases. No 429 was observed.
The observations span a short local experiment, not a long-term stability test
or an IP-independent access guarantee. No challenge was solved, no rate limit
was bypassed and no repeat search loop was attempted.

## Performance and resources

Measurements are approximate local Windows values. Process-tree RSS sums the
Python process, Playwright driver and browser children; shared pages can be
counted more than once. It is not a measured Linux cgroup usage or a per-request
incremental memory cost. Driver startup is excluded from browser launch timing.

| Measurement | Observed |
| --- | --- |
| Browser launch | Headless shell 0.324 s; headed Chromium 0.159–0.495 s |
| Headed post DOMContentLoaded | 0.683–3.271 s |
| Headed post ready for initial article capture | 1.204–3.793 s |
| Headed post observation including scrolling | 5.044–9.866 s; initial long-post comparison used one scroll, remaining matrix used three |
| Headed search observation | 12.891–13.755 s, no results |
| Successful headed-post network requests | 604–645 per fresh context, mostly 530–612 static asset requests to `abs.twimg.com`; counts include blocked requests |
| Headless-shell requests | One document request per case; all 403 |
| Peak headed process-tree RSS | 1,262–1,348 MiB, approximately 1.23–1.32 GiB |
| Peak headless-shell process-tree RSS | 436.1 MiB, without a functioning page |
| Peak full headless Chromium RSS | 613.7–627.1 MiB, without a functioning page |
| Uncached HTTP comparison | Approximately 0.5–3.3 s per post; reader normally makes one document fetch |

The first headless-shell version waited for DOM content even after 403,
so its 12–16 s observation times reflect the diagnostic wait, not successful
rendering. The final script now stops promptly on 401/403/429. Much of the
headed network cost was normal frontend asset loading, not explicit API retries.
Media downloads were blocked in the later run, but manifest/XHR behavior can
still produce video-host requests. No browser-reuse/caching optimization or
server concurrency benchmark was attempted. HTTP-reader memory was not
benchmarked separately; it has no browser process overhead.

## Docker and Synology implications

The isolated packages are `playwright`, `pyee`, `greenlet`, `typing-extensions`
and diagnostic-only `psutil`. Browser binaries and platform OS libraries are
additional dependencies. The local Windows download included full Chromium,
headless shell and FFmpeg: about **311.5 MiB downloaded**, **705.6 MiB unpacked**.
These are measured Windows artifacts, not the size of a Linux image layer.
A rough planning allowance is several hundred MiB to over 1 GiB for browser,
driver and Linux libraries together; exact Linux image growth is unmeasured.

The existing image is `python:3.13-slim`, runs as a nonroot `mcp` user, and
currently installs only `ca-certificates` as an OS package. It is not ready to
run Chromium simply by adding a Python dependency. Browser libraries, writable
temporary/profile directories, a functioning sandbox/seccomp configuration,
adequate shared memory, RAM and supported CPU architecture would need review.
The [official Playwright Docker guidance](https://playwright.dev/python/docs/docker)
describes browser/OS dependencies and nonroot/seccomp requirements for crawling.
Its prebuilt testing image is not automatically a production solution for this
server. Browser variants are described in the
[official browser documentation](https://playwright.dev/python/docs/browsers).

A Linux display service such as Xvfb would also be needed to reproduce headed
execution in a container without a desktop; **this combination was not tested**.
The Windows headed success therefore cannot be extrapolated to Synology.
No NAS architecture, available memory, Docker sandbox compatibility or Linux
browser behavior was probed. Do not disable browser sandboxing merely to make
it launch. No Dockerfile or NAS setting was changed.

## Tests and final scope

The complete existing suite passes: **176 tests**. Existing tests were not
edited in this phase. The PoC is intentionally separate from normal tests.
`git diff --check` passes. No production browser provider, MCP tool, dependency,
commit, push or deployment was added. Earlier uncommitted X/OAuth work remains
in the working tree.

The evidence meets the requested *content-value* thresholds for a visible
browser (long text, six posts, quote context). It does **not** meet an unattended
NAS integration threshold. If browser development is pursued later, the next
question is controlled anonymous Linux/container reproducibility and resource
limits, rather than more blind search retries or private API reconstruction.

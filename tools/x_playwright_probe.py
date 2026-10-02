"""Isolated anonymous X browser experiment; never imported by the MCP server.

Install Playwright and psutil in a separate venv. Set PLAYWRIGHT_BROWSERS_PATH
to an ignored directory. Results contain public page data only, no network
headers, cookies, request bodies, storage, HAR or authentication values.
"""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import x_public

HOSTS = x_public.X_HOSTS | {
    "abs.twimg.com", "pbs.twimg.com", "video.twimg.com", "api.x.com",
    "api.twitter.com", "cdn.syndication.twimg.com", "platform.twitter.com",
}

DOM = r"""() => {
  const links = node => Array.from(node.querySelectorAll('a[href]')).map(a => ({
    text: a.innerText.slice(0, 300), href: a.getAttribute('href')
  })).slice(0, 100);
  const body = document.body?.innerText || '';
  return {
    title: document.title, body_text: body.slice(0, 16000),
    articles: Array.from(document.querySelectorAll('article')).slice(0, 50).map(a => ({
      text: a.innerText.slice(0, 16000),
      tweet_texts: Array.from(a.querySelectorAll('[data-testid="tweetText"]')).map(t => t.innerText),
      text_blocks: Array.from(a.querySelectorAll('[dir="auto"],p')).map(t => t.innerText).filter(Boolean).slice(0,80),
      nested_articles: a.querySelectorAll('article').length,
      author_blocks: Array.from(a.querySelectorAll('[data-testid="User-Name"]')).map(t => t.innerText),
      times: Array.from(a.querySelectorAll('time')).map(t => ({datetime:t.dateTime, text:t.innerText})),
      links: links(a),
      images: Array.from(a.querySelectorAll('img')).map(i => ({src:i.currentSrc,alt:i.alt})).slice(0,30),
      videos: Array.from(a.querySelectorAll('video')).map(v => ({src:v.currentSrc,poster:v.poster})),
      labels: Array.from(a.querySelectorAll('[aria-label]')).map(n => n.getAttribute('aria-label')).slice(0,60),
      testids: Array.from(new Set(Array.from(a.querySelectorAll('[data-testid]')).map(n => n.dataset.testid)))
    })),
    status_links: links(document).filter(l => /\/status\/\d+/.test(l.href || '')),
    testids: Array.from(new Set(Array.from(document.querySelectorAll('[data-testid]')).map(n => n.dataset.testid))).slice(0,100),
    jsonld: Array.from(document.querySelectorAll('script[type="application/ld+json"]')).map(s => {
      try {return JSON.parse(s.textContent)} catch {return null}
    }).slice(0,10),
    embedded_json_scripts: document.querySelectorAll('script[type="application/json"]').length,
    meta: Object.fromEntries(Array.from(document.querySelectorAll('meta[property^="og:"],meta[name="description"]'))
      .map(m => [m.getAttribute('property') || m.name,m.content]))
  };
}"""


def public_tweets(document):
    """Whitelist only tweet fields from JSON already received by the page.

    No API requests are constructed and no headers, guest tokens or cookies
    are inspected or retained. Recursive traversal is bounded.
    """
    found = {}
    stack = [document]
    visited = 0
    while stack and visited < 20000:
        item = stack.pop()
        visited += 1
        if isinstance(item, list):
            stack.extend(item[:500])
        elif isinstance(item, dict):
            legacy = item.get("legacy", {})
            if isinstance(legacy, dict) and legacy.get("full_text") and item.get("rest_id"):
                user = item.get("core", {}).get("user_results", {}).get("result", {})
                user = user.get("legacy", {}) if isinstance(user, dict) else {}
                found[item["rest_id"]] = {
                    "post_id": item["rest_id"], "text": legacy["full_text"],
                    "username": user.get("screen_name"), "author": user.get("name"),
                    "created_at": legacy.get("created_at"),
                    "reply_to": legacy.get("in_reply_to_status_id_str"),
                    "conversation_id": legacy.get("conversation_id_str"),
                    "quote_id": legacy.get("quoted_status_id_str"),
                }
            stack.extend(item.values())
    return list(found.values())[:100]


def page_gate(snapshot):
    text = snapshot.get("body_text", "").lower()
    if any(s in text for s in ("verify you are human", "captcha", "unusual activity", "access denied")):
        return "challenge"
    if not snapshot.get("articles") and "accept all cookies" in text:
        return "cookie_consent_gate"
    if not snapshot.get("articles") and any(s in text for s in
            ("sign in to x", "log in to x", "anmelden bei x", "sign in", "log in", "anmelden")):
        return "login_gate"
    return None


async def run(args):
    from playwright.async_api import async_playwright, Error
    import psutil

    # Pin every permitted destination before Chromium starts; reject private DNS.
    pins, unavailable = {}, []
    for host in sorted(HOSTS):
        try:
            pins[host] = (await asyncio.to_thread(x_public.public_addresses, host, 443))[0]
        except (OSError, x_public.XError):
            unavailable.append(host)
    rules = ",".join(f"MAP {host} {address}" for host, address in pins.items())
    cases = [(f"post_{n+1}", x_public.normalize_url(u)[0]) for n, u in enumerate(args.urls)]
    cases.extend((f"search_{q}", "https://x.com/search?" + urlencode({"q": q, "src": "typed_query"}))
                 for q in args.search)
    report = {"date": datetime.now(timezone.utc).isoformat(), "headless": not args.headed,
              "full_chromium": args.full_chromium,
              "versions": {p: importlib.metadata.version(p) for p in ("playwright", "psutil")},
              "unresolved_hosts": unavailable, "cases": [],
              "limitations": ["DOM relationships are observations, not a proven thread graph/end.",
                              "RSS is process working-set sum, shared pages may be counted twice."]}
    peak = 0
    sampling = True

    async def sample_ram():
        nonlocal peak
        process = psutil.Process()
        while sampling:
            total = 0
            for child in [process, *process.children(recursive=True)]:
                try:
                    total += child.memory_info().rss
                except psutil.Error:
                    pass
            peak = max(peak, total)
            await asyncio.sleep(.25)

    monitor = asyncio.create_task(sample_ram())
    try:
        async with async_playwright() as pw:
            start = time.perf_counter()
            browser = await pw.chromium.launch(headless=not args.headed, chromium_sandbox=True,
                channel="chromium" if args.full_chromium else None,
                args=["--disable-quic", "--disable-background-networking", "--disable-component-update",
                      "--host-resolver-rules=" + rules])
            report["browser_start_seconds"] = round(time.perf_counter() - start, 3)
            report["browser_version"] = browser.version
            for label, url in cases:
                result = {"label": label, "url": url, "snapshots": [], "json_observations": [],
                          "requests_by_host": {}, "responses": {}, "scrolls": 0,
                          "blocked_requests": 0, "failed_requests": 0}
                if "/status/" in url:
                    start = time.perf_counter()
                    provider = x_public.FreePublicProvider()
                    provider.cache = None
                    try:
                        result["http_reader"] = await provider.read_post(url, refresh=True)
                    except x_public.XError as exc:
                        result["http_reader"] = x_public.failure(exc.code, exc.message)
                    except Exception as exc:
                        result["http_reader"] = {"ok": False, "error_type": type(exc).__name__}
                    result["http_seconds"] = round(time.perf_counter() - start, 3)
                # Fresh ephemeral context per URL; no storage import or persistence.
                context = await browser.new_context(accept_downloads=False, service_workers="block",
                    viewport={"width": 1280, "height": 900}, locale="en-US")
                hosts, statuses, tasks = Counter(), Counter(), []

                async def guard(route):
                    parsed = urlsplit(route.request.url)
                    if (parsed.scheme != "https" or parsed.hostname not in pins or parsed.port not in (None,443)
                            or route.request.resource_type == "media" or sum(hosts.values()) > 1000):
                        result["blocked_requests"] += 1
                        await route.abort()
                    else:
                        await route.continue_()

                await context.route("**/*", guard)
                await context.route_web_socket("**/*", lambda ws: ws.close())
                page = await context.new_page()
                page.on("dialog", lambda dialog: dialog.dismiss())
                page.on("request", lambda request: hosts.update([urlsplit(request.url).hostname or "unknown"]))
                page.on("requestfailed", lambda request: result.__setitem__("failed_requests", result["failed_requests"]+1))

                async def observe(response):
                    statuses.update([str(response.status)])
                    # Response headers are accessed only for type/length, never recorded wholesale.
                    ctype = response.headers.get("content-type", "").split(";")[0]
                    length = response.headers.get("content-length")
                    if ctype == "application/json" and response.status == 200 and len(result["json_observations"]) < 40:
                        if length and int(length) > 2 * 1024 * 1024:
                            return
                        try:
                            body = await response.body()
                            if len(body) > 2 * 1024 * 1024:
                                return
                            data = json.loads(body)
                            result["json_observations"].append({"host":urlsplit(response.url).hostname,
                                "status":response.status,"content_type":ctype,
                                "top_level_keys":list(data)[:20] if isinstance(data,dict) else [],
                                "public_tweets":public_tweets(data)})
                        except (ValueError, Error):
                            pass

                page.on("response", lambda response: tasks.append(asyncio.create_task(observe(response))))
                start = time.perf_counter()
                try:
                    response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    result["initial_status"] = response.status if response else None
                    if response:
                        result["document_metadata"] = {key: response.headers.get(key) for key in
                            ("content-type", "content-length", "server")}
                    result["domcontentloaded_seconds"] = round(time.perf_counter()-start,3)
                    for _ in range(24):
                        await asyncio.sleep(.5)
                        snap = await page.evaluate(DOM)
                        if snap["articles"] or page_gate(snap) or result["initial_status"] in (401,403,429):
                            break
                    result["settled_seconds"] = round(time.perf_counter()-start,3)
                    result["snapshots"].append(snap)
                    result["gate"] = ("http_access_denied" if result["initial_status"] in (401,403) else
                                      "http_rate_limit" if result["initial_status"] == 429 else page_gate(snap))
                    if not result["gate"] and snap["articles"]:
                        for _ in range(args.scrolls):
                            await page.mouse.wheel(0, 1000)
                            result["scrolls"] += 1
                            await asyncio.sleep(2)
                            snap = await page.evaluate(DOM)
                            result["snapshots"].append(snap)
                            result["gate"] = page_gate(snap)
                            if result["gate"]:
                                break
                    result["final_host_path"] = urlsplit(page.url).hostname + urlsplit(page.url).path
                except Error as exc:
                    result["browser_error_type"] = type(exc).__name__
                    network_error = re.search(r"net::ERR_[A-Z_]+", str(exc))
                    result["network_error_code"] = network_error.group() if network_error else None
                    # No raw exception/network URL parameters stored.
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                result["total_seconds"] = round(time.perf_counter()-start,3)
                result["requests_by_host"] = dict(hosts)
                result["responses"] = dict(statuses)
                await context.close()
                report["cases"].append(result)
                print(json.dumps({"case":label,"status":result.get("initial_status"),
                    "gate":result.get("gate"),"articles": max([len(s["articles"]) for s in result["snapshots"]] or [0]),
                    "requests":sum(hosts.values()),"seconds":result["total_seconds"]}),flush=True)
                args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                await asyncio.sleep(2)
            await browser.close()
    finally:
        sampling = False
        await monitor
        report["peak_process_tree_rss_mib"] = round(peak / (1024 * 1024),1)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output":str(args.output),"peak_rss_mib":report["peak_process_tree_rss_mib"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="*", help="Public X/Twitter status URLs only")
    parser.add_argument("--search", action="append", default=[], help="Public search term; no login attempted")
    parser.add_argument("--scrolls", type=int, choices=range(0,7), default=3)
    parser.add_argument("--headed", action="store_true", help="Optional visibly launched clean Chromium")
    parser.add_argument("--full-chromium", action="store_true", help="Use full Chromium instead of the headless shell")
    parser.add_argument("--output", type=Path, default=Path(".venv/x-playwright-results.json"))
    options = parser.parse_args()
    if not options.urls and not options.search:
        parser.error("Supply a status URL or --search term")
    # Keep public data diagnostics inside ignored local paths.
    root = Path(__file__).resolve().parents[1] / ".venv"
    if not options.output.resolve().is_relative_to(root):
        parser.error("--output must be within the project's ignored .venv directory")
    options.output.parent.mkdir(parents=True,exist_ok=True)
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(root / "x-playwright-browsers"))
    asyncio.run(run(options))

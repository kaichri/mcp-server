"""Explicit, budgeted diagnostic: one search, one single read, one batch read.

Load config.env in the calling shell first. Does not repeat Deep or Auto tests.
Results stay in memory and each completed call is checkpointed before proceeding.
"""
import asyncio
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exa_provider import Config, DirectExaApiProvider, ExaError, ExaRouter, SearchRequest, checked_urls


class AuditedDirect(DirectExaApiProvider):
    def __init__(self, key):
        super().__init__(key)
        self.requests = []

    async def _post(self, endpoint, payload, timeout=25):
        event = {"method": "POST", "endpoint": "/" + endpoint,
                 "num_results": payload.get("numResults"), "urls": payload.get("urls")}
        self.requests.append(event)
        try:
            data = await super()._post(endpoint, payload, timeout)
            event["http_status"] = 200
            return data
        except ExaError as error:
            event["http_status"] = error.status
            raise


class ForbiddenRemote:
    async def search(self, *args, **kwargs):
        raise ExaError("EXA_UNAVAILABLE", reason="unexpected_remote_call")

    async def contents(self, *args, **kwargs):
        raise ExaError("EXA_UNAVAILABLE", reason="unexpected_remote_call")


async def complete(report, provider, router, save, clock=time.perf_counter):
    """No report reassignment in nested closures; safe summaries never replace results."""
    async def check(name, operation):
        started = clock()
        before = len(provider.requests)
        result = None
        try:
            result = await operation()
            pages = result["results"]
            ok = (result["provider"] == "exa_direct" and not result["fallbacks"]
                  and bool(pages) and all(not p.get("error") and p.get("url") and p.get("title")
                                         and p.get("text") for p in pages))
            event = {"name": name, "status": "OK" if ok else "FAIL", "provider": result["provider"],
                     "fallbacks": result["fallbacks"], "usage": result["usage"], "result_count": len(pages),
                     "results": [{"url": p["url"], "requested_url": p.get("requested_url"),
                                  "title": p["title"], "text_characters": len(p["text"]),
                                  "text_utf8_bytes": len(p["text"].encode()), "preview": p["text"][:200],
                                  "error": p.get("error")} for p in pages]}
            if name.endswith("contents"):
                wanted = provider.requests[before]["urls"]
                event["url_mapping_correct"] = [p.get("requested_url") for p in pages] == wanted
                if not event["url_mapping_correct"]:
                    event["status"] = "FAIL"
        except ExaError as error:
            event = {"name": name, "status": "FAIL", "provider": "exa_direct", "error": error.as_dict()}
        event["seconds"] = round(clock() - started, 3)
        event["requests"] = provider.requests[before:]
        # Preserve the original failed harness attempt as history, not the current result.
        old = next((t for t in report["tests"] if t["name"] == name), None)
        if old and old.get("status") == "UNVERIFIED":
            report.setdefault("historical_attempts", []).append(old)
        report["tests"] = [t for t in report["tests"] if t["name"] != name] + [event]
        report["additional_requests"] = len(provider.requests)
        report["request_attempts_total"] = 3 + len(provider.requests)
        save(report)
        return result

    search = await check("direct_search", lambda: router.search(SearchRequest("Qwen 3.8 Flash Next", 3)))
    if search is None:
        return report
    urls = []
    for page in search["results"]:
        url = page.get("url")
        try:
            checked_urls([url])
        except ExaError:
            continue
        if url not in urls:
            urls.append(url)
    report["search_has_two_usable_urls"] = len(urls) >= 2
    save(report)
    if len(urls) < 2:
        return report
    await check("single_contents", lambda: router.contents([urls[0]]))
    await check("batch_contents", lambda: router.contents(urls[:2]))
    return report


def main():
    key = os.getenv("EXA_API_KEY", "")
    if not key:
        raise SystemExit("EXA_API_KEY missing; no requests or report changes made.")
    logging.disable(logging.CRITICAL)
    os.environ["EXA_PROVIDER"] = "direct"
    path = Path(__file__).resolve().parents[1] / "docs/exa-direct-live-smoke.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["completion_date"] = datetime.now(timezone.utc).isoformat()
    provider = AuditedDirect(key)
    router = ExaRouter(Config.from_env(), ForbiddenRemote(), direct=provider)
    def save(value):
        encoded = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        if key in encoded:
            raise RuntimeError("Secret echo detected; report withheld.")
        path.write_text(encoded, encoding="utf-8")
    asyncio.run(complete(report, provider, router, save))
    print(json.dumps({"additional_requests": len(provider.requests),
                      "tests": [{"name": t["name"], "status": t["status"], "seconds": t.get("seconds"),
                                 "usage": t.get("usage")} for t in report["tests"]]}))


if __name__ == "__main__":
    main()

"""CLI-only comparison harness for the experimental shared BrowserReader."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.web_reader_poc import BrowserReader, Cache, ExaReader, FetchPipeline, validate_destination

CASES = [
    ("static","https://example.com/"),
    ("js_news","https://www.theverge.com/tech/1003877/apple-security-camera-no-video"),
    ("technical_blog","https://blog.cloudflare.com/18-november-2025-outage/"),
    ("forum","https://discuss.python.org/t/python-3-13-0-final-has-been-released/66972"),
    ("x_long","https://x.com/Alibaba_Qwen/status/1886105723047973138"),
    ("x_thread","https://x.com/kchonyc/status/1978156587320803734"),
]


async def run(args):
    import psutil
    from server import call_exa
    logging.disable(logging.CRITICAL)  # No remote SDK session/header logging.
    browser = BrowserReader(headed=args.headed)
    pipeline = FetchPipeline(ExaReader(call_exa),browser,cache=Cache(str(ROOT/".venv/web-reader-poc.sqlite3")))
    report = {"date":datetime.now(timezone.utc).isoformat(),"headed":args.headed,"cases":[],
              "browser_start_seconds":None,"note":"Readability is not proof of completeness."}
    running = True
    current_peak = peak = 0

    async def monitor():
        nonlocal current_peak,peak
        process = psutil.Process()
        while running:
            total = 0
            for child in [process,*process.children(recursive=True)]:
                try:
                    total += child.memory_info().rss
                except psutil.Error:
                    pass
            current_peak = max(current_peak,total)
            peak = max(peak,total)
            await asyncio.sleep(.2)

    task = asyncio.create_task(monitor())
    cases = [(name,url) for name,url in CASES if not args.only or name in args.only]
    try:
        for name,url in cases:
            case = {"label":name,"url":url,"readers":{}}
            for mode in ("exa","http","browser"):
                current_peak = 0
                start = time.perf_counter()
                value = await pipeline.fetch(url,mode,refresh=args.refresh)
                case["readers"][mode] = value
                value["probe_elapsed_seconds"] = round(time.perf_counter()-start,3)
                value["peak_tree_rss_mib"] = round(current_peak/1024/1024,1)
                print(json.dumps({"case":name,"mode":mode,"length":value["content_length"],
                    "quality":value["quality"],"cached":value["cached"],"error":value.get("error"),
                    "seconds":value["probe_elapsed_seconds"],"requests":value.get("diagnostics",{}).get("requests","remote_unknown")}),flush=True)
                await asyncio.sleep(1)
            exa,observed_browser = case["readers"]["exa"],case["readers"]["browser"]
            candidates = [exa] if exa["quality"]["sufficient"] else [exa,observed_browser]
            selected = max(candidates,key=lambda v:(v["quality"]["sufficient"],v["quality"]["score"]))
            case["auto_decision_from_measured_candidates"] = selected["source"]
            report["cases"].append(case)
            args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        if args.search:
            # The public MCP schema requires objective; production web_search is untouched.
            start = time.perf_counter()
            try:
                raw = await asyncio.wait_for(call_exa("web_search_exa",{
                    "query":args.search,"objective":"Find relevant primary-source pages for the query.","numResults":3}),35)
                report["exa_search"] = {"query":args.search,"content":raw[:20000],
                                        "seconds":round(time.perf_counter()-start,3)}
            except Exception as error:
                report["exa_search"] = {"query":args.search,"error_type":type(error).__name__}
        # One genuine auto request plus cache hit: no browser should start on adequate Exa content.
        if args.auto_check:
            url = "https://example.com/"
            first = await pipeline.fetch(url,"auto",refresh=True)
            second = await pipeline.fetch(url,"auto")
            report["auto_and_cache_check"] = {"first":first,"second":second}
    finally:
        await browser.close()
        running = False
        await task
        report["browser_start_seconds"] = browser.start_seconds
        report["peak_tree_rss_mib"] = round(peak/1024/1024,1)
        report["proxy_connections"] = browser.proxy.connections
        report["opaque_tunnel_bytes"] = browser.proxy.bytes
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"output":str(args.output),"peak_tree_rss_mib":report["peak_tree_rss_mib"]}),flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headed",action="store_true")
    parser.add_argument("--refresh",action="store_true")
    parser.add_argument("--only",action="append",choices=[c[0] for c in CASES])
    parser.add_argument("--search",help="One experimental Exa search; never browser search")
    parser.add_argument("--auto-check",action="store_true")
    parser.add_argument("--output",type=Path,default=ROOT/".venv/web-reader-results.json")
    options = parser.parse_args()
    if not options.output.resolve().is_relative_to(ROOT/".venv"):
        parser.error("Output must stay within the ignored .venv directory")
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH",str(ROOT/".venv/x-playwright-browsers"))
    asyncio.run(run(options))

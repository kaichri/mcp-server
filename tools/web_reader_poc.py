"""Experimental Exa-first content pipeline; deliberately not a registered MCP tool.

Playwright/psutil are optional diagnostic dependencies imported only on launch.
The production server, its tool schemas and its dependencies remain unchanged.
"""
import asyncio
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
import http.client
import ipaddress
import json
from pathlib import Path
import re
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

from x_public import Cache, FreePublicProvider, XError, checked_url, public_addresses

MAX_TEXT = 20000
MAX_HTML = 2 * 1024 * 1024
BLOCK_TAGS = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg"}
GATE = re.compile(r"^(?:enable javascript|javascript (?:is )?required|please sign in|sign in to continue|"
                  r"log in to continue|verify you are human|access denied|just a moment|"
                  r"accept all cookies|loading(?:\.{3}|…)?$)", re.I)
TRACKERS = {"google-analytics.com", "googletagmanager.com", "doubleclick.net", "googlesyndication.com",
            "scorecardresearch.com", "hotjar.com", "sentry.io", "taboola.com", "outbrain.com"}
BOILERPLATE_CLASS = re.compile(r"(?:^|[-_ ])(?:ads?|advertisement|cookie|share|social|newsletter|related|popular|recirculation)(?:[-_ ]|$)",re.I)


def validated_url(url):
    """Generic HTTPS policy using the existing URL and public-DNS primitives."""
    try:
        host = urlsplit(url).hostname
        parsed = checked_url(url, {host})
        if parsed.scheme != "https" or not host or host == "localhost" or host.endswith((".localhost", ".local")):
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host:
                raise ValueError()
        else:
            if not address.is_global or address.is_multicast or address.is_reserved:
                raise ValueError()
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))
    except (ValueError, TypeError, XError):
        raise XError("UNSUPPORTED_URL", "Only public HTTPS destinations and standard ports are allowed.") from None


async def validate_destination(url):
    url = validated_url(url)
    await asyncio.wait_for(asyncio.to_thread(public_addresses, urlsplit(url).hostname, 443), 5)
    return url


def result(url, source, content="", **fields):
    value = {"url": url, "canonical_url": url, "title": None, "author": None,
             "published_at": None, "updated_at": None, "content": content[:MAX_TEXT],
             "source": source, "browser_used": source == "browser", "complete": False,
             "completeness": "unknown" if content else "unavailable", "headings": [],
             "links": [], "media": [], "tables": [], "code_blocks": [],
             "fetched_at": datetime.now(timezone.utc).isoformat(), "cached": False}
    value.update(fields)
    if len(content) > MAX_TEXT:
        value["truncated"] = True
    # Bound the entire structured payload, not only its main text.
    for name in ("tables","links","media","code_blocks","headings","visible_posts"):
        while len(json.dumps(value,ensure_ascii=False).encode("utf-8")) > 128 * 1024 and value.get(name):
            value[name].pop()
            value["truncated"] = True
    value["content_length"] = len(value["content"])
    value["quality"] = quality(value)
    return value


def error_code(error):
    pending = [error]
    while pending:
        item = pending.pop()
        if isinstance(item,BaseExceptionGroup):
            pending.extend(item.exceptions)
            continue
        text = str(item).lower()
        for pattern,code in ((r"rate.limit|too many requests|\b429\b","RATE_LIMITED"),
                             (r"input validation|invalid arguments","REMOTE_SCHEMA"),
                             (r"no content|not found|could not fetch|failed to fetch","NO_CONTENT"),
                             (r"access denied|forbidden|\b403\b","ACCESS_DENIED")):
            if re.search(pattern,text):
                return code
        match = re.search(r"mcp error (-\d+)",text)
        if match:
            return "MCP_REMOTE_ERROR_"+match[1]
    return type(error).__name__


def quality(value):
    """Sufficiency for reading, never a proof of completeness."""
    text = value.get("content", "").strip()
    reasons, score = [], 0
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    intro = re.sub(r"^#+\s*", "", lines[0]) if lines else ""
    if value.get("error") or value.get("gate"):
        reasons.append("fetch_error_or_access_gate")
    if not text:
        reasons.append("empty")
    elif len(text) < 80:
        reasons.append("very_short")
    if GATE.match(intro) or GATE.match(value.get("title") or ""):
        reasons.append("javascript_login_consent_or_challenge")
    if value.get("extractor") == "meta":
        reasons.append("meta_preview_only")
    if urlsplit(value.get("url", "")).hostname in {"x.com", "twitter.com", "www.x.com"}:
        if value.get("extractor") != "x" and len(text) < 500:
            reasons.append("possible_x_preview")
    boilerplate = sum(bool(re.fullmatch(r"(?:home|menu|privacy|terms|subscribe|sign in|cookies|contact)", l, re.I))
                      for l in lines)
    if lines and boilerplate / len(lines) > .5:
        reasons.append("navigation_dominates")
    if len(lines) > 20 and sum(len(line) == 1 for line in lines) / len(lines) > .4:
        reasons.append("fragmented_rendered_text")
    if value.get("incomplete_extraction"):
        reasons.append("incomplete_extraction")
    if value.get("truncated"):
        reasons.append("local_content_limit")
    if text and not any(r in reasons for r in ("fetch_error_or_access_gate", "javascript_login_consent_or_challenge")):
        score = min(60, len(text) // 80) + (15 if value.get("title") else 0) + 20
        score -= 25 * sum(r in reasons for r in ("very_short", "meta_preview_only", "navigation_dominates", "possible_x_preview"))
    return {"sufficient": not reasons, "score": max(0, score), "reasons": reasons,
            "meaning": "heuristic_readability_not_verified_completeness"}


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def nodes(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.nodes()

    def content_nodes(self):
        if self.tag in BLOCK_TAGS or BOILERPLATE_CLASS.search(self.attrs.get("class", "")):
            return
        yield self
        for child in self.children:
            if isinstance(child,Node):
                yield from child.content_nodes()

    def text(self, filtered=True):
        if filtered and (self.tag in BLOCK_TAGS or BOILERPLATE_CLASS.search(self.attrs.get("class", ""))):
            return ""
        if filtered and "data-poc-rendered-text" in self.attrs:
            return self.attrs["data-poc-rendered-text"]
        parts = [(c.text(filtered) if isinstance(c, Node) else c) for c in self.children]
        separator = "\n" if self.tag in {"article", "main", "div", "section", "p", "ul", "li", "pre", "table", "tr"} else ""
        return separator.join(p for p in parts if p.strip()).strip()


class Document(HTMLParser):
    def __init__(self, html, rendered=False):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]
        self.count = 0
        self.rendered = rendered
        self.feed(html[:MAX_HTML])

    def handle_starttag(self, tag, attrs):
        self.count += 1
        if self.count > 30000 or len(self.stack) > 200:
            raise XError("CONTENT_LIMIT", "Document structure exceeds diagnostic limits.")
        node = Node(tag, dict(attrs))
        if not self.rendered:
            node.attrs.pop("data-poc-rendered-text",None)
        self.stack[-1].children.append(node)
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def metadata(nodes, url):
    meta = {n.attrs.get("property", n.attrs.get("name")): n.attrs.get("content") for n in nodes if n.tag == "meta"}
    title = next((n.text(False) for n in nodes if n.tag == "title"), None)
    canonical = next((n.attrs.get("href") for n in nodes if n.tag == "link" and "canonical" in n.attrs.get("rel", "").split()), url)
    try:
        canonical = validated_url(urljoin(url, canonical or url))
    except XError:
        canonical = url
    fields = {"canonical_url": canonical, "title": meta.get("og:title") or title,
              "author": meta.get("author"), "published_at": meta.get("article:published_time"),
              "updated_at": meta.get("article:modified_time")}
    pending = []
    for node in nodes:
        if node.tag == "script" and node.attrs.get("type") == "application/ld+json":
            try:
                pending.append(json.loads(node.text(False)))
            except ValueError:
                pass
    for _ in range(100):
        if not pending:
            break
        item = pending.pop()
        if isinstance(item, list):
            pending.extend(item[:50])
        elif isinstance(item, dict):
            kinds = item.get("@type", [])
            kinds = [kinds] if isinstance(kinds, str) else kinds
            if any(k in {"Article", "NewsArticle", "BlogPosting", "TechArticle", "DiscussionForumPosting"} for k in kinds):
                author = item.get("author")
                if isinstance(author, list):
                    author = author[0] if author else None
                if isinstance(author, dict):
                    author = author.get("name")
                for key, val in (("author", author), ("published_at", item.get("datePublished")),
                                 ("updated_at", item.get("dateModified")), ("title", item.get("headline"))):
                    if val and not fields.get(key) and isinstance(val, str):
                        fields[key] = val[:500]
            graph = item.get("@graph", [])
            if isinstance(graph, list):
                pending.extend(graph[:50])
    return fields, meta


def extract_html(html, url, source="http"):
    """One extractor router for both HTTP HTML and the browser's rendered HTML."""
    doc = Document(html,rendered=source=="browser")
    nodes = list(doc.root.nodes())
    fields, meta = metadata(nodes, url)
    articles = [n for n in nodes if n.tag == "article"]
    is_x = urlsplit(url).hostname in {"x.com", "www.x.com", "twitter.com"}
    forum = (any("topic-post" in n.attrs.get("class", "").split() for n in nodes)
             or "discourse" in (meta.get("generator") or "").lower())
    extractor = "x" if is_x else "forum" if forum else "article"
    if is_x or forum:
        selected = ([n for n in nodes if "cooked" in n.attrs.get("class", "").split()
                     or n.attrs.get("itemprop") == "text"] if forum else articles)
        selected = selected or [n for n in nodes if "topic-post" in n.attrs.get("class", "").split()]
        # Parent article already contains the nested quote; do not count it twice.
        selected = [n for n in selected if not any(n is sub for parent in selected if parent is not n
                                                  for sub in list(parent.nodes())[1:])][:30]
        roots = selected
    else:
        bodies = [n for n in nodes if n.attrs.get("itemprop") == "articleBody"]
        mains = [n for n in nodes if n.tag == "main" or n.attrs.get("role") == "main"]
        roots = bodies[:1] or sorted(articles, key=lambda n: len(n.text()), reverse=True)[:1] or mains[:1]
    if not roots:
        roots = [next((n for n in nodes if n.tag == "body"), doc.root)]
    visible_posts = []
    if is_x and articles:
        def own_nodes(root):
            yield root
            for child in root.children:
                if isinstance(child,Node) and child.tag != "article":
                    yield from own_nodes(child)
        for root in roots:
            own = list(own_nodes(root))
            status = next(((n,re.fullmatch(r"/([A-Za-z0-9_]+)/status/([0-9]+)",urlsplit(urljoin(url,n.attrs.get("href",""))).path))
                           for n in own if n.tag == "a" and re.fullmatch(r"/[A-Za-z0-9_]+/status/[0-9]+",urlsplit(urljoin(url,n.attrs.get("href",""))).path)),None)
            if not status:
                continue
            anchor,match = status
            username,post_id = match.groups()
            blocks = [n.text() for n in own if n.attrs.get("dir") == "auto" and n.text()]
            author = next((n.text() for n in own if n.tag=="a" and n.attrs.get("href")=="/"+username
                           and n.text() and not n.text().startswith("@")),None)
            visible_posts.append({"post_id":post_id,"username":username,"author":author,
                                  "text":"\n".join(blocks)[:MAX_TEXT],"displayed_time":anchor.text(),
                                  "url":"https://x.com/"+username+"/status/"+post_id})
        wanted = re.search(r"/status/([0-9]+)",urlsplit(url).path)
        main = next((p for p in visible_posts if wanted and p["post_id"]==wanted[1]),None)
        if main:
            fields["author"] = main["author"]
            main_root = next(root for root in roots if any(n.tag=="a" and n.attrs.get("href")=="/"+main["username"]+"/status/"+main["post_id"] for n in own_nodes(root)))
            roots = [main_root]
    text = "\n\n".join(n.text() for n in roots)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n", "\n\n", text).strip()
    if is_x and visible_posts and main and main["text"]:
        text = main["text"]
    gate_text = " ".join(n.text() for n in roots)[:500].strip()
    gate = "access_or_script_gate" if GATE.match(gate_text) or GATE.match(fields.get("title") or "") else None
    if not text and meta.get("description", meta.get("og:description")):
        text = meta.get("description", meta.get("og:description"))
        extractor = "meta"
    main_nodes = [n for root in roots for n in root.content_nodes()]
    links, media, headings, tables, code = [], [], [], [], []
    for node in main_nodes:
        if re.fullmatch("h[1-6]", node.tag):
            headings.append({"level": int(node.tag[1]), "text": node.text()[:1000]})
        if node.tag == "a" and node.attrs.get("href"):
            target = urljoin(url, node.attrs["href"])
            if urlsplit(target).scheme in {"http", "https"}:
                links.append({"text": node.text()[:300], "url": target[:1024]})
        if node.tag in {"img", "video"}:
            src = node.attrs.get("src", "")
            media.append({"type": node.tag, "url": urljoin(url,src)[:1024] if src else None,
                          "alt": node.attrs.get("alt", "")[:300], "poster": node.attrs.get("poster", "")[:1024] or None})
        if node.tag == "table":
            rows = [r for r in node.nodes() if r.tag == "tr"][:20]
            tables.append([[c.text()[:1000] for c in r.children if isinstance(c, Node) and c.tag in {"td", "th"}][:20] for r in rows])
        if node.tag == "pre":
            code.append(node.text(False)[:4000])
    return result(url, source, text, **fields, extractor=extractor, gate=gate,
                  headings=headings[:50], links=links[:100], media=media[:40], tables=tables[:10],
                  code_blocks=code[:20], truncated=len(text) > MAX_TEXT or len(html) > MAX_HTML,
                  incomplete_extraction=bool(forum and not selected),
                  visible_posts=visible_posts[:20],
                  observed_top_level_articles=len(roots) if is_x or forum else None)


class HttpReader:
    def _fetch(self, url):
        deadline = time.monotonic() + 20
        for _ in range(5):
            url = validated_url(url)
            parsed = urlsplit(url)
            address = public_addresses(parsed.hostname, 443)[0]
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise XError("TIMEOUT", "HTTP reader timed out.")
            connection = http.client.HTTPSConnection(parsed.hostname, timeout=min(8,remaining), context=ssl.create_default_context())
            connection._create_connection = lambda destination, timeout, source_address=None: socket.create_connection((address,443),timeout,source_address)
            try:
                connection.request("GET", parsed.path + ("?"+parsed.query if parsed.query else ""),
                                   headers={"User-Agent":"PublicMCPReader/1.0","Accept":"text/html","Accept-Encoding":"identity"})
                response = connection.getresponse()
                if response.status in {301,302,303,307,308}:
                    location = response.getheader("Location")
                    if not location:
                        raise XError("REDIRECT", "Missing redirect destination.")
                    url = validated_url(urljoin(url,location))
                    continue
                if response.status != 200:
                    return result(url,"http",error={"code":"HTTP_STATUS","status":response.status})
                if response.getheader("Content-Type", "").split(";")[0] not in {"text/html","application/xhtml+xml"}:
                    raise XError("CONTENT_TYPE", "Unsupported HTML response type.")
                chunks, size = [],0
                while True:
                    if time.monotonic() > deadline:
                        raise XError("TIMEOUT", "HTTP body timed out.")
                    chunk = response.read1(min(65536,MAX_HTML+1-size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > MAX_HTML:
                        raise XError("CONTENT_LIMIT", "HTML exceeds 2 MiB.")
                value = extract_html(b"".join(chunks).decode("utf-8",errors="replace"),url)
                value["http_status"] = 200
                value["diagnostics"] = {"requests":_+1,"document_bytes":size}
                return value
            finally:
                connection.close()
        raise XError("REDIRECT", "Too many redirects.")

    async def read(self,url):
        if urlsplit(url).hostname in {"x.com","twitter.com","www.x.com"}:
            provider = FreePublicProvider()
            provider.cache = None
            original = await provider.read_post(url,refresh=True)
            post = original["post"]
            return result(url,"http",post["text"],canonical_url=post["url"],author=post["author_name"],
                          published_at=post["published_at"],media=post["media"],
                          extractor="meta" if post["source"] == "meta" else "x",
                          completeness=post["completeness"],diagnostics={"requests":1})
        return await asyncio.wait_for(asyncio.to_thread(self._fetch,url),25)


class ExaReader:
    def __init__(self, call):
        self.call = call

    async def read(self,url):
        await validate_destination(url)
        # Current remote schema adapter is confined to this PoC.
        raw = await asyncio.wait_for(self.call("web_fetch_exa",{"urls":[url],"maxCharacters":MAX_TEXT}),35)
        title = next((line[2:].strip() for line in raw.splitlines() if line.startswith("# ")),None)
        content = re.sub(r"(?m)^URL:.*\n?", "", raw).strip()
        fields = {}
        for key,label in (("author","Author"),("published_at","Published (?:Date|Time)"),("updated_at","Updated (?:Date|Time)")):
            match = re.search(r"(?m)^"+label+r":\s*(.+)$", raw)
            fields[key] = match[1][:500] if match else None
        return result(url,"exa",content,title=title,**fields,truncated=len(content)>=MAX_TEXT)


class PublicTunnelProxy:
    """Local diagnostic CONNECT proxy; DNS-pinned public destinations, opaque TLS.

    This does not decrypt TLS, inspect credentials or log HTTP headers. Chromium
    verifies target certificates. WebSockets and non-HTTPS requests are rejected
    by context routing. Runtime request/body budgets remain essential.
    """
    def __init__(self):
        self.server = None
        self.tasks = set()
        self.dns = {}
        self.connections = 0
        self.bytes = 0

    async def start(self):
        self.server = await asyncio.start_server(self.handle,"127.0.0.1",0,limit=16384)
        return "http://127.0.0.1:"+str(self.server.sockets[0].getsockname()[1])

    async def handle(self,reader,writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        upstream = None
        try:
            self.connections += 1
            if self.connections > 3000 or self.bytes > 256 * 1024 * 1024:
                return
            header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"),5)
            first = header.split(b"\r\n",1)[0].decode("ascii")
            method,target,_ = first.split(" ")
            if method != "CONNECT":
                return
            parsed = urlsplit("https://"+target)
            url = validated_url("https://"+target)
            host = parsed.hostname
            if host not in self.dns:
                self.dns[host] = await asyncio.wait_for(asyncio.to_thread(public_addresses,host,443),5)
            address = self.dns[host][0]
            incoming,upstream = await asyncio.wait_for(asyncio.open_connection(address,443),8)
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()

            async def pump(source,destination):
                amount = 0
                while True:
                    data = await source.read(65536)
                    if not data:
                        return
                    amount += len(data)
                    self.bytes += len(data)
                    if amount > 32 * 1024 * 1024 or self.bytes > 256 * 1024 * 1024:
                        return
                    destination.write(data)
                    await destination.drain()
            pumps = [asyncio.create_task(pump(reader,upstream)),asyncio.create_task(pump(incoming,writer))]
            try:
                await asyncio.wait(pumps,timeout=45,return_when=asyncio.FIRST_COMPLETED)
            finally:
                for p in pumps:
                    p.cancel()
                await asyncio.gather(*pumps,return_exceptions=True)
        except (OSError,ValueError,UnicodeError,XError,asyncio.TimeoutError,asyncio.IncompleteReadError,asyncio.LimitOverrunError):
            pass
        finally:
            if upstream:
                upstream.close()
            writer.close()
            self.tasks.discard(task)

    async def close(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        pending = list(self.tasks)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending,return_exceptions=True)


class BrowserReader:
    """One browser process, one isolated context per read; generic and X extraction."""
    def __init__(self,headed=False):
        self.headed = headed
        self.slots = asyncio.Semaphore(1)
        self.lock = asyncio.Lock()
        self.proxy = PublicTunnelProxy()
        self.browser = self.playwright = None
        self.start_seconds = None

    async def start(self):
        async with self.lock:
            if self.browser:
                return
            from playwright.async_api import async_playwright
            start = time.perf_counter()
            endpoint = await self.proxy.start()
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(headless=not self.headed,chromium_sandbox=True,
                proxy={"server":endpoint,"bypass":"<-loopback>"},
                args=["--disable-quic","--disable-background-networking","--disable-component-update",
                      "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                      "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"])
            self.start_seconds = round(time.perf_counter()-start,3)

    async def read(self,url):
        url = await validate_destination(url)
        async with self.slots:
            await self.start()
            context = await self.browser.new_context(accept_downloads=False,service_workers="block",
                locale="en-US",viewport={"width":1280,"height":900})
            stats = {"requests":0,"blocked":0,"statuses":Counter(),"scrolls":0}
            start = time.perf_counter()
            initial_status = None

            async def guard(route):
                stats["requests"] += 1
                host = urlsplit(route.request.url).hostname or ""
                try:
                    validated_url(route.request.url)
                    if stats["requests"] > 1000 or route.request.resource_type in {"font","media"}:
                        raise ValueError()
                    if any(host == h or host.endswith("."+h) for h in TRACKERS):
                        raise ValueError()
                    # The tunnel proxy does the authoritative DNS check and pinned connect.
                    await route.continue_()
                except (XError,ValueError):
                    stats["blocked"] += 1
                    await route.abort()

            await context.route("**/*",guard)
            await context.route_web_socket("**/*",lambda ws:ws.close())
            page = await context.new_page()
            page.on("dialog",lambda dialog:dialog.dismiss())
            page.on("response",lambda response:stats["statuses"].update([str(response.status)]))
            try:
                async with asyncio.timeout(25):
                    response = await page.goto(url,wait_until="domcontentloaded",timeout=18000)
                    initial_status = response.status if response else None
                    dcl_seconds = round(time.perf_counter()-start,3)
                    if initial_status in {401,403,429}:
                        value = result(url,"browser",error={"code":"HTTP_STATUS","status":initial_status})
                    else:
                        await asyncio.sleep(2)
                        if urlsplit(url).hostname in {"x.com","twitter.com"}:
                            for _ in range(2):
                                await page.mouse.wheel(0,1000)
                                stats["scrolls"] += 1
                                await asyncio.sleep(1)
                        final = validated_url(page.url)
                        # Only in-browser DOM inspection; scripts never executed outside Chromium.
                        html = await page.evaluate("""() => {
                            const clone=document.documentElement.cloneNode(true);
                            const originals=Array.from(document.documentElement.querySelectorAll('*'));
                            const copies=Array.from(clone.querySelectorAll('*'));
                            if (originals.length>30000) throw new Error('DOM limit');
                            for(let i=0;i<originals.length;i++){
                                const original=originals[i],copy=copies[i],style=getComputedStyle(original);
                                if(original.closest('body')&&!original.matches('script[type="application/ld+json"]')
                                   &&(style.display==='none'||style.visibility==='hidden')){copy.remove();continue;}
                                if(original.matches('p,pre,h1,h2,h3,h4,h5,h6,[dir="auto"]'))
                                    copy.setAttribute('data-poc-rendered-text',(original.innerText||'').slice(0,40000));
                            }
                            clone.querySelectorAll('script:not([type="application/ld+json"]),style,noscript,iframe,form').forEach(n=>n.remove());
                            return clone.outerHTML.slice(0,2097153);
                        }""")
                        value = extract_html(html,final,"browser")
                        value["url"] = url
                        value["initial_status"] = initial_status
                    value["domcontentloaded_seconds"] = dcl_seconds
            except Exception as error:
                code = re.search(r"net::ERR_[A-Z_]+",str(error))
                value = result(url,"browser",error={"code":code[0] if code else type(error).__name__})
            finally:
                await context.close()
            value["elapsed_seconds"] = round(time.perf_counter()-start,3)
            value["diagnostics"] = {**stats,"statuses":dict(stats["statuses"])}
            return value

    async def close(self):
        try:
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        finally:
            await self.proxy.close()


class FetchPipeline:
    def __init__(self,exa,browser,http=None,cache=None):
        self.readers = {"exa":exa,"http":http or HttpReader(),"browser":browser}
        self.cache = cache

    async def fetch(self,url,mode="auto",refresh=False):
        return await asyncio.wait_for(self._fetch(url,mode,refresh),65)

    async def _fetch(self,url,mode,refresh):
        if mode not in {"auto","exa","http","browser"}:
            raise ValueError("Unknown fetch mode")
        url = await validate_destination(url)
        browser_config = getattr(self.readers['browser'],'headed',False) if mode in {"auto","browser"} else "unused"
        version = "v1" if mode == "exa" else "v2" if mode == "http" else "v3"
        key = f"web-reader-poc:{version}:{mode}:{url}:headed={browser_config}"
        cached = await asyncio.to_thread(self.cache.get,key) if self.cache and not refresh else None
        if cached:
            cached["cached"] = True
            return cached
        attempts = []
        for source in (["exa","browser"] if mode == "auto" else [mode]):
            start = time.perf_counter()
            try:
                value = await self.readers[source].read(url)
            except Exception as error:
                value = result(url,source,error={"code":error_code(error)})
            value["reader_elapsed_seconds"] = round(time.perf_counter()-start,3)
            attempts.append(value)
            if mode != "auto" or value["quality"]["sufficient"]:
                break
        # Prefer adequate content, then quality score. Exa wins exact ties.
        best = max(attempts,key=lambda v:(v["quality"]["sufficient"],v["quality"]["score"]))
        best["attempts"] = [{"source":v["source"],"quality":v["quality"],"error":v.get("error")} for v in attempts]
        best["browser_attempted"] = any(v["browser_used"] for v in attempts)
        if self.cache and not best.get("error") and not best.get("gate"):
            await asyncio.to_thread(self.cache.put,key,best,1800 if best["quality"]["sufficient"] else 60)
        return best

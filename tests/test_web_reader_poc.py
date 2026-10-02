"""Offline behavior/security tests; no browser install or live network required."""
import asyncio
import json

import pytest

from tools import web_reader_poc as poc


@pytest.mark.parametrize("url",[
    "http://example.com/", "file:///etc/passwd", "https://localhost/",
    "https://127.0.0.1/", "https://10.0.0.1/", "https://[::1]/", "https://router.local/",
    "https://user:password@example.com/", "https://example.com:8443/", "https://example.com/\nheader",
])
def test_generic_url_policy_refuses_unsafe_destinations(url):
    with pytest.raises(poc.XError):
        poc.validated_url(url)


def test_destination_reuses_public_dns_guard(monkeypatch):
    def denied(host,port):
        raise poc.XError("UNSUPPORTED_URL","Private DNS destination")
    monkeypatch.setattr(poc,"public_addresses",denied)
    with pytest.raises(poc.XError):
        asyncio.run(poc.validate_destination("https://public-looking.example/"))


def test_quality_distinguishes_gate_from_article_about_login():
    gate = poc.result("https://example.com/","exa","Enable JavaScript")
    assert not gate["quality"]["sufficient"]
    article = poc.result("https://example.com/","exa","Login security explained\n"+"This explains sign in and consent. "*40)
    assert article["quality"]["sufficient"]
    assert article["complete"] is False
    assert article["completeness"] == "unknown"


def test_meta_preview_and_fragmented_dom_are_not_quality_content():
    preview = poc.result("https://example.com/","http","Preview text "*30,extractor="meta")
    assert "meta_preview_only" in preview["quality"]["reasons"]
    fragments = poc.result("https://example.com/","browser","\n".join("fragmented"*20))
    assert "fragmented_rendered_text" in fragments["quality"]["reasons"]


def test_article_extracts_metadata_tables_code_and_excludes_navigation_ads():
    html = '''<html><head><title>Article</title><link rel="canonical" href="/canonical">
    <script type="application/ld+json">{"@type":"NewsArticle","author":{"name":"Sample Author"},
    "datePublished":"2026-10-01T10:00:00Z","dateModified":"2026-10-02T11:00:00Z"}</script></head>
    <body><nav><a href="/nav">NAVIGATION ONLY</a></nav><article><h1>Useful article</h1>
    <p>Actual body content with sufficient detail to read and analyze safely.</p>
    <div class="related-stories"><a href="/ad">UNRELATED AD TEXT</a></div>
    <a href="/source">Source</a><img src="/photo.jpg" alt="Sample image">
    <table><tr><th>Key</th><th>Value</th></tr><tr><td>A</td><td>1</td></tr></table>
    <pre><code>print("example")</code></pre><script>TEMP_SCRIPT_PAYLOAD</script></article></body></html>'''
    value = poc.extract_html(html,"https://example.com/article")
    assert value["canonical_url"] == "https://example.com/canonical"
    assert value["author"] == "Sample Author"
    assert value["published_at"] == "2026-10-01T10:00:00Z"
    assert value["updated_at"] == "2026-10-02T11:00:00Z"
    assert value["tables"][0] == [["Key","Value"],["A","1"]]
    assert value["code_blocks"] == ['print("example")']
    assert value["media"][0]["alt"] == "Sample image"
    assert all(s not in value["content"] for s in ("NAVIGATION ONLY","UNRELATED AD TEXT","TEMP_SCRIPT_PAYLOAD"))
    assert all("/ad" not in link["url"] and "/nav" not in link["url"] for link in value["links"])


def test_forum_chooses_post_bodies_not_an_embedded_article():
    html = '''<meta name="generator" content="Discourse 3.4"><body><main>
    <div class="cooked"><p>First complete forum post.</p><article>Embedded link preview</article></div>
    <div class="cooked"><p>Second author's reply.</p></div></main></body>'''
    value = poc.extract_html(html,"https://forum.example/t/topic/1")
    assert value["extractor"] == "forum"
    assert value["observed_top_level_articles"] == 2
    assert "First complete forum post" in value["content"]
    assert "Second author's reply" in value["content"]
    assert value["complete"] is False


def test_x_nested_quote_does_not_become_an_extra_thread_post():
    html = '''<body><article><p>Author's post</p><article><p>Quoted author's text</p></article></article>
    <article><p>Continuation</p></article></body>'''
    value = poc.extract_html(html,"https://x.com/sample/status/123","browser")
    assert value["observed_top_level_articles"] == 2
    assert value["content"].count("Quoted author's text") == 1
    assert value["complete"] is False


def test_x_main_body_and_visible_candidates_are_separate():
    html = '''<body><article><a href="/sample">Sample Author</a><p dir="auto">Main post body</p>
    <a href="/sample/status/123">Oct 1</a></article>
    <article><a href="/sample">Sample Author</a><p dir="auto">Continuation candidate</p>
    <a href="/sample/status/124">Oct 1</a></article>
    <article><a href="/other">Other Author</a><p dir="auto">Foreign reply candidate</p>
    <a href="/other/status/125">Oct 1</a></article></body>'''
    value = poc.extract_html(html,"https://x.com/sample/status/123","browser")
    assert value["content"] == "Main post body"
    assert value["author"] == "Sample Author"
    assert [p["post_id"] for p in value["visible_posts"]] == ["123","124","125"]
    assert value["complete"] is False


def test_remote_error_classification_never_returns_raw_message():
    error = ExceptionGroup("outer",[RuntimeError("MCP error -32602: Input validation error")])
    assert poc.error_code(error) == "REMOTE_SCHEMA"


def test_rendered_text_annotation_is_browser_only():
    html = '<article><p data-poc-rendered-text="Readable text">R<div>e</div>a<div>d</div></p></article>'
    assert poc.extract_html(html,"https://example.com/","browser")["content"] == "Readable text"
    assert poc.extract_html(html,"https://example.com/","http")["content"] != "Readable text"


def test_structured_payload_and_text_are_bounded():
    value = poc.result("https://example.com/","browser","x"*40000,
                       tables=[[["y"*1000]*20]*20]*10,links=[{"url":"z"*4000}]*100)
    assert value["content_length"] == 20000
    assert len(json.dumps(value).encode()) < 130*1024
    assert "local_content_limit" in value["quality"]["reasons"]


class Reader:
    def __init__(self,value):
        self.value = value
        self.calls = 0
    async def read(self,url):
        self.calls += 1
        return dict(self.value)


@pytest.fixture
def no_network(monkeypatch):
    async def validate(url):
        return poc.validated_url(url)
    monkeypatch.setattr(poc,"validate_destination",validate)


def test_auto_keeps_adequate_exa_and_never_launches_browser(no_network):
    exa = Reader(poc.result("https://example.com/","exa","Useful content "*100))
    browser = Reader(poc.result("https://example.com/","browser","More content "*100))
    value = asyncio.run(poc.FetchPipeline(exa,browser).fetch("https://example.com/"))
    assert value["source"] == "exa"
    assert browser.calls == 0
    assert value["browser_attempted"] is False


def test_auto_fallback_and_cache_refresh(no_network,tmp_path):
    exa = Reader(poc.result("https://example.com/","exa","Enable JavaScript"))
    browser = Reader(poc.result("https://example.com/","browser","Actual article content "*100))
    pipeline = poc.FetchPipeline(exa,browser,cache=poc.Cache(str(tmp_path/"web.sqlite3")))
    first = asyncio.run(pipeline.fetch("https://example.com/"))
    second = asyncio.run(pipeline.fetch("https://example.com/"))
    assert first["source"] == "browser" and first["browser_used"]
    assert second["cached"] and second["fetched_at"] == first["fetched_at"]
    assert exa.calls == browser.calls == 1
    asyncio.run(pipeline.fetch("https://example.com/",refresh=True))
    assert exa.calls == browser.calls == 2


def test_failed_browser_does_not_replace_useful_exa_preview(no_network):
    exa = Reader(poc.result("https://x.com/sample/status/123","exa","Public preview "*10))
    browser = Reader(poc.result("https://x.com/sample/status/123","browser",error={"code":"BLOCKED"}))
    value = asyncio.run(poc.FetchPipeline(exa,browser).fetch("https://x.com/sample/status/123"))
    assert value["source"] == "exa"
    assert value["browser_used"] is False and value["browser_attempted"] is True


def test_exa_adapter_uses_current_schema_without_changing_legacy_tool(no_network):
    calls = []
    async def call(name,arguments):
        calls.append((name,arguments))
        return "# Test Article\nURL: https://example.com/\n\nActual article content "*10
    value = asyncio.run(poc.ExaReader(call).read("https://example.com/"))
    assert calls == [("web_fetch_exa",{"urls":["https://example.com/"],"maxCharacters":20000})]
    assert value["source"] == "exa"
    assert value["complete"] is False


def test_tunnel_pins_public_dns_and_rejects_local_connect(monkeypatch):
    connected = []
    class Writer:
        def __init__(self): self.data = b""
        def write(self,data): self.data += data
        async def drain(self): pass
        def close(self): pass
    async def connect(address,port):
        connected.append((address,port))
        incoming = asyncio.StreamReader()
        incoming.feed_eof()
        return incoming,Writer()
    monkeypatch.setattr(poc,"public_addresses",lambda host,port:["93.184.215.14"])
    monkeypatch.setattr(asyncio,"open_connection",connect)
    async def attempt(target):
        proxy = poc.PublicTunnelProxy()
        incoming = asyncio.StreamReader()
        incoming.feed_data(f"CONNECT {target} HTTP/1.1\r\n\r\n".encode())
        incoming.feed_eof()
        writer = Writer()
        await proxy.handle(incoming,writer)
        return writer.data
    assert b"200 Connection Established" in asyncio.run(attempt("example.com:443"))
    assert connected == [("93.184.215.14",443)]
    assert asyncio.run(attempt("127.0.0.1:443")) == b""
    assert len(connected) == 1

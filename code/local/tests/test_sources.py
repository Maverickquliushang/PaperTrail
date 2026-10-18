import json

import httpx
import pytest
from pydantic import ValidationError

from backend.models import SearchRequest, now
from backend.sources import Providers, SourceError, arxiv_id, doi_id, parse_arxiv, parse_openalex, safe_url
from backend.sources import parse_openreview
from backend.models import Record
from backend.search import merge_records


def test_openreview_acceptance_and_dates_are_not_submission_or_workshop():
    def note(venueid, **kwargs):
        return {"id": "abc", "content": {"venueid": {"value": venueid}, "title": {"value": "Test"},
                "pdf": {"value": "/pdf?id=abc"}}, "cdate": 1704067200000, **kwargs}
    data = {"notes": [note("ICLR.cc/2025/Conference", pdate=1735689600000),
        note("ICLR.cc/2025/Conference/Rejected_Submission"), note("ICLR.cc/2025/Conference/Withdrawn_Submission"),
        note("ICLR.cc/2025/Workshop/Test"), note("ICLR.cc/2025/Conference", replyto="abc"),
        note("ICML.cc/2025/Conference")]}
    records = parse_openreview(data, now(), ["ICLR"])
    assert len(records) == 1 and records[0].conference == "ICLR"
    assert records[0].publication_date == "2025-01-01" and records[0].submitted_date == "2024-01-01"
    assert records[0].pdf_url == "https://openreview.net/pdf?id=abc"
    assert parse_openreview({"notes": [note("ICLR.cc/2025/Conference")]}, now(), ["ICLR"])[0].publication_date is None


async def test_conference_query_uses_dblp_without_openalex_credentials():
    def handler(request):
        assert request.url.host == 'sparql.dblp.org'
        assert 'Authorization' not in request.headers
        assert 'streams/conf/cvpr' in request.url.params['query']
        return httpx.Response(200,json={'results':{'bindings':[{
            'paper':{'value':'https://dblp.org/rec/conf/cvpr/test'},
            'title':{'value':'Test paper'},'year':{'value':'2025'},'conference':{'value':'CVPR'}}]}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        data=await Providers(client,'private-key').search('conferences',SearchRequest(query='test',conferences=['CVPR']))
        assert data.records[0].conference=='CVPR'
        assert data.records[0].publication_year==2025
        assert data.records[0].publication_date is None


def test_conference_index_does_not_double_count_openalex():
    base = Record(source="openalex", source_id="https://openalex.org/W1", title="Paper", url="https://openalex.org/W1", retrieved_at=now())
    merged = merge_records([base, base.model_copy(update={"source": "conferences", "conference": "CVPR"})], "relevance")
    assert len(merged) == 1 and merged[0]["score"] == pytest.approx(1 / 61)


async def test_openreview_filters_dates_inside_candidates():
    def handler(request):
        assert request.url.params["group"] == "ICLR.cc" and request.url.params["limit"] == "100"
        return httpx.Response(200, json={"notes": [{"id": "old", "pdate": 1735689600000, "content": {"venueid": {"value": "ICLR.cc/2025/Conference"}, "title": {"value": "old"}}}], "count": 300})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        data = await Providers(client).search("openreview", SearchRequest(query="test", conferences=["ICLR"], start_date="2026-01-01"))
    assert data.records == [] and data.limited and data.total is None and data.scanned == 1


def test_query_validation_and_dates():
    with pytest.raises(ValidationError):
        SearchRequest(query="   ")
    with pytest.raises(ValidationError):
        SearchRequest(query="test", sources=[])
    with pytest.raises(ValidationError):
        SearchRequest(query="test", start_date="2026-10-10", end_date="2026-09-10")
    with pytest.raises(ValidationError):
        SearchRequest(query="test", limit=500)
    assert SearchRequest(query=" test  query ").query == "test query"


def test_identifiers_and_links():
    assert arxiv_id("https://arxiv.org/pdf/2401.12345v3.pdf") == "2401.12345"
    assert arxiv_id("https://example.com/2401.12345") is None
    assert arxiv_id("10.48550/arXiv.hep-th/9901001") == "hep-th/9901001"
    assert doi_id("https://doi.org/10.1000/ABC") == "10.1000/abc"
    assert safe_url("javascript:alert(1)") is None


def test_arxiv_preserves_submission_revision_and_publication_semantics():
    xml = b'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:o="http://a9.com/-/spec/opensearch/1.1/" xmlns:x="http://arxiv.org/schemas/atom">
    <o:totalResults>4</o:totalResults><entry><id>http://arxiv.org/abs/2401.12345v2</id><title> Paper\n title </title>
    <summary>Original abstract</summary><published>2024-01-01T00:00:00Z</published><updated>2025-02-01T00:00:00Z</updated>
    <x:doi>10.1000/TEST</x:doi><author><name>Alice</name></author><link title="pdf" href="https://arxiv.org/pdf/2401.12345"/></entry></feed>'''
    records, total = parse_arxiv(xml, now())
    assert total == 4
    assert records[0].title == "Paper title"
    assert records[0].submitted_date == "2024-01-01"
    assert records[0].updated_date == "2025-02-01"
    assert records[0].publication_date is None
    assert records[0].doi == "10.1000/test"


def test_openalex_abstract_and_identity_from_locations():
    record = {"id": "https://openalex.org/W1", "title": "Test", "doi": "https://doi.org/10.1000/abc",
              "publication_date": "2025-02-01", "updated_date": "2026-10-01", "primary_location": None,
              "locations": [{"landing_page_url": "https://arxiv.org/abs/2401.12345v2"}],
              "abstract_inverted_index": {"second": [1], "first": [0]}, "authorships": []}
    records, total = parse_openalex({"results": [record], "meta": {"count": 12}}, now())
    assert total == 12
    assert records[0].abstract == "first second"
    assert records[0].arxiv_id == "2401.12345"
    assert records[0].publication_date == "2025-02-01"
    assert records[0].updated_date is None


def test_arxiv_html_error_is_not_an_empty_search():
    with pytest.raises(ValueError, match="Atom"):
        parse_arxiv(b"<html><body>Service unavailable</body></html>", now())


async def test_hf_filters_paper_date_not_listing_date_and_reports_bound():
    def handler(request):
        assert request.url.params["limit"] == "120"
        assert request.url.params["q"] == "test"
        return httpx.Response(200, json=[
            {"paper": {"id": "2401.12345", "title": "Old paper", "publishedAt": "2024-01-01", "ai_summary": "Not original"}, "publishedAt": "2026-10-01"},
            {"paper": {"id": "2601.12345", "title": "Recent paper", "publishedAt": "2026-01-01", "summary": "Original"}},
        ])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        data = await Providers(client).search("huggingface", SearchRequest(query="test", start_date="2026-01-01"))
    assert [r.title for r in data.records] == ["Recent paper"]
    assert data.limited and data.total is None and data.scanned == 2


async def test_date_parameters_sent_to_remote_sources():
    seen = []
    def handler(request):
        seen.append(request)
        if request.url.host == "api.openalex.org":
            return httpx.Response(200, json={"results": [], "meta": {"count": 0}})
        return httpx.Response(200, content=b'<feed xmlns="http://www.w3.org/2005/Atom" xmlns:o="http://a9.com/-/spec/opensearch/1.1/"><o:totalResults>0</o:totalResults></feed>')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        providers = Providers(client, "secret-test-value")
        query = SearchRequest(query='vision "test"', start_date="2026-01-01", end_date="2026-02-01", sort="date")
        await providers.search("arxiv", query)
        await providers.search("openalex", query)
    assert 'submittedDate:[202601010000 TO 202602012359]' in seen[0].url.params["search_query"]
    assert seen[0].url.params["sortBy"] == "submittedDate"
    assert seen[1].url.params["filter"] == "from_publication_date:2026-01-01,to_publication_date:2026-02-01"
    assert seen[1].headers["authorization"] == "Bearer secret-test-value"
    assert "secret-test-value" not in str(seen[1].url)


async def test_access_error_does_not_echo_upstream_secrets():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401, text="secret-test-value"))) as client:
        with pytest.raises(SourceError) as exc:
            await Providers(client, "secret-test-value").search("openalex", SearchRequest(query="test"))
    assert exc.value.code == "access_denied"
    assert "secret-test-value" not in str(exc.value)


async def test_long_retry_after_is_not_ignored():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"retry-after": "3600"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError) as exc:
            await Providers(client).search("openalex", SearchRequest(query="test"))
    assert exc.value.code == "rate_limited"
    assert len(calls) == 1


async def test_openalex_scoped_search_and_future_dates_are_rejected(monkeypatch):
    from datetime import date
    import backend.sources as sources
    monkeypatch.setattr(sources, "effective_end_date", lambda request: min(request.end_date or date(2026, 10, 18), date(2026, 10, 18)))
    seen = []
    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"results": [
            {"id": "Wfuture", "title": "Future Low Rank Decomposition", "publication_date": "2026-12-31"},
            {"id": "Wrecent", "title": "Low Rank Decomposition for Language Models", "publication_date": "2026-10-17"},
            {"id": "Wold", "title": "Old Low Rank Decomposition", "publication_date": "2026-01-01"}], "meta": {"count": 3}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        providers = Providers(client)
        data = await providers.search("openalex", SearchRequest(query="low rank decomposition", sort="date"))
        assert seen[-1]["search.title_and_abstract"] == "low rank decomposition" and "search" not in seen[-1]
        assert seen[-1]["filter"] == "to_publication_date:2026-10-18"
        assert [r.source_id for r in data.records] == ["Wrecent", "Wold"]
        assert "已排除 1 条" in data.note
        data = await providers.search("openalex", SearchRequest(query="low rank decomposition", start_date="2026-10-01", end_date="2027-12-31"))
        assert seen[-1]["filter"] == "from_publication_date:2026-10-01,to_publication_date:2026-10-18"
        assert [r.source_id for r in data.records] == ["Wrecent"]
        before = len(seen)
        data = await providers.search("openalex", SearchRequest(query="test", start_date="2027-01-01"))
        assert not data.records and "晚于今天" in data.note and len(seen) == before


async def test_future_dates_filtered_in_local_candidate_sources(monkeypatch):
    from datetime import date, datetime, timezone
    import backend.sources as sources
    monkeypatch.setattr(sources, "effective_end_date", lambda request: date(2026, 10, 18))
    def handler(request):
        if request.url.host == "huggingface.co":
            return httpx.Response(200, json=[
                {"paper": {"id": "2612.12345", "title": "Future", "publishedAt": "2026-12-31"}},
                {"paper": {"id": "2610.12345", "title": "Past", "publishedAt": "2026-10-17"}}])
        return httpx.Response(200, json={"notes": [{"id": name, "pdate": int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()*1000),
                "content": {"title": {"value": name}, "venueid": {"value": "ICLR.cc/2026/Conference"}}}
                for name,day in [("future","2026-12-31"),("past","2026-10-17")]]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        p = Providers(client)
        for source in ["huggingface", "openreview"]:
            data = await p.search(source, SearchRequest(query="test", conferences=["ICLR"], sort="date"))
            assert len(data.records) == 1 and data.records[0].filter_date == "2026-10-17"


async def test_arxiv_default_date_ceiling_is_remote_and_local(monkeypatch):
    from datetime import date
    import backend.sources as sources
    monkeypatch.setattr(sources, "effective_end_date", lambda request: date(2026, 10, 18))
    def handler(request):
        assert 'submittedDate:[199101010000 TO 202610182359]' in request.url.params['search_query']
        return httpx.Response(200, content=b'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:o="http://a9.com/-/spec/opensearch/1.1/">
        <o:totalResults>2</o:totalResults>
        <entry><id>https://arxiv.org/abs/2612.12345</id><title>Future</title><published>2026-12-31</published></entry>
        <entry><id>https://arxiv.org/abs/2610.12345</id><title>Past</title><published>2026-10-17</published></entry>
        </feed>''')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        data = await Providers(client).search("arxiv", SearchRequest(query="test"))
        assert [r.title for r in data.records] == ["Past"]


def test_cache_does_not_preview_pre_fix_queries_and_rolls_over_at_midnight(tmp_path, monkeypatch):
    import hashlib
    from datetime import date
    import backend.search as search
    from backend.models import SourceData
    request = SearchRequest(query="low rank decomposition", sort="date")
    data = SourceData(records=[], retrieved_at=now())
    old_digest = hashlib.sha256(json.dumps(request.model_dump(mode="json", exclude={"sources"}), sort_keys=True).encode()).hexdigest()
    (tmp_path / f"v1-openalex-{old_digest}.json").write_text(data.model_dump_json())
    cache = search.Cache(tmp_path)
    monkeypatch.setattr(search, "effective_end_date", lambda request: date(2026,10,18))
    assert cache.read("openalex",request) is None
    cache.write("openalex",request,data)
    assert cache.read("openalex",request) is not None
    monkeypatch.setattr(search, "effective_end_date", lambda request: date(2026,10,19))
    assert cache.read("openalex",request) is None

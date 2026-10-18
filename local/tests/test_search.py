import asyncio

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.models import Record, SearchRequest, SourceData, now
from backend.search import Cache, SearchService, merge_records
from backend.sources import SourceError


def record(source="arxiv", source_id="id1", **kwargs):
    return Record(source=source, source_id=source_id, title="Same title", url="https://example.org/paper", retrieved_at=now(), **kwargs)


def test_transitive_exact_identity_merge_and_no_title_merge():
    records = [record(arxiv_id="2401.12345"), record("openalex", "W1", doi="10.1000/test"),
               record("huggingface", "2401.12345", arxiv_id="2401.12345", doi="10.1000/test"), record("arxiv", "id2")]
    merged = merge_records(records, "relevance")
    assert len(merged) == 2
    combined = next(p for p in merged if len(p["sources"]) == 3)
    assert len(combined["evidence"]) == 3
    assert len({e["source"] for e in combined["evidence"]}) == 3


async def test_partial_failure_and_progress_before_all_complete(tmp_path):
    gate = asyncio.Event()
    class FakeProviders:
        async def search(self, source, request):
            if source == "openalex":
                await gate.wait()
                raise SourceError("rate_limited", "限流")
            return SourceData(records=[record(source)], retrieved_at=now())
    service = SearchService(FakeProviders(), Cache(tmp_path))
    task = service.create(SearchRequest(query="test", sources=["arxiv", "openalex"]))
    for _ in range(30):
        if task.statuses["arxiv"].state == "success":
            break
        await asyncio.sleep(.001)
    assert not task.done and len(task.snapshot()["papers"]) == 1
    gate.set()
    await task.runner
    assert task.done
    assert task.statuses["openalex"].state == "error"
    assert len(task.snapshot()["papers"]) == 1


async def test_cache_is_marked_and_live_failure_not_hidden(tmp_path):
    request = SearchRequest(query="test", sources=["arxiv"])
    cache = Cache(tmp_path)
    cached_at = "2026-01-01T00:00:00+00:00"
    cached_record = record().model_copy(update={"retrieved_at": cached_at})
    cache.write("arxiv", request, SourceData(records=[cached_record], retrieved_at=cached_at))
    class FailingProviders:
        async def search(self, *args):
            raise SourceError("timeout", "超时")
    service = SearchService(FailingProviders(), cache)
    task = service.create(request)
    assert task.snapshot()["papers"][0]["evidence"][0]["cached"]
    await task.runner
    assert task.statuses["arxiv"].state == "error"
    assert task.statuses["arxiv"].cached_at == cached_at
    assert "缓存" in task.statuses["arxiv"].note


async def test_successful_empty_refresh_clears_stale_cache(tmp_path):
    cache = Cache(tmp_path)
    query = SearchRequest(query="test", sources=["arxiv"])
    cache.write("arxiv", query, SourceData(records=[record()], retrieved_at=now()))
    class EmptyProviders:
        async def search(self, *args):
            return SourceData(records=[], total=0, retrieved_at=now())
    task = SearchService(EmptyProviders(), cache).create(query)
    await task.runner
    assert task.snapshot()["papers"] == []
    assert task.statuses["arxiv"].cached_at is None


async def test_cancel_releases_capacity_and_finishes_status(tmp_path):
    class SlowProviders:
        async def search(self, *args):
            await asyncio.sleep(100)
    service = SearchService(SlowProviders(), Cache(tmp_path))
    tasks = [service.create(SearchRequest(query="test")) for _ in range(4)]
    with pytest.raises(SourceError, match="4"):
        service.create(SearchRequest(query="overflow"))
    await asyncio.sleep(.01)
    await service.close()
    assert all(t.done for t in tasks)
    assert all(s.state == "cancelled" for t in tasks for s in t.statuses.values())


async def test_invalid_upstream_response_is_error(tmp_path):
    class BrokenProviders:
        async def search(self, *args):
            raise ValueError("secret-value")
    task = SearchService(BrokenProviders(), Cache(tmp_path)).create(SearchRequest(query="test", sources=["arxiv"]))
    await task.runner
    assert task.statuses["arxiv"].error_code == "invalid_response"
    assert "secret-value" not in str(task.snapshot())


def test_local_api_validation_health_and_origin():
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.post("/api/searches", json={"query": "test", "sources": []}).status_code == 422
        assert client.post("/api/searches", json={"query": "test"}, headers={"Origin": "https://unrelated.example"}).status_code == 403
        assert client.get("/api/searches/missing").status_code == 404


def test_sse_completes_and_retains_evidence(tmp_path):
    class FakeProviders:
        async def search(self, source, request):
            return SourceData(records=[record(source, arxiv_id="2401.12345")], retrieved_at=now())
    with TestClient(app) as client:
        app.state.search = SearchService(FakeProviders(), Cache(tmp_path))
        response = client.post("/api/searches", json={"query": "test", "sources": ["arxiv"]})
        assert response.status_code == 202
        identifier = response.json()["id"]
        events = client.get(f"/api/searches/{identifier}/events")
        assert "text/event-stream" in events.headers["content-type"]
        assert "event: snapshot" in events.text and '"done": true' in events.text
        assert client.get(f"/api/searches/{identifier}").json()["papers"][0]["arxiv_id"] == "2401.12345"

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app import app
from backend.models import Record, SearchRequest, SourceData, now
from backend.recommendations import BEIJING, RecommendationService, RecommendationSettings
from backend.search import Cache, SearchService
from backend.sources import SourceError


class FakeProviders:
    failing = set()

    async def search(self, source, request):
        if source in self.failing:
            raise SourceError("timeout", "模拟超时")
        return SourceData(records=[Record(source=source, source_id="same", title="Transformer retrieval",
            arxiv_id="2601.12345", url="https://arxiv.org/abs/2601.12345",
            submitted_date=str(request.end_date), publication_date=str(request.end_date), retrieved_at=now())], retrieved_at=now())


def service(tmp_path, sources=None):
    search = SearchService(FakeProviders(), Cache(tmp_path / "cache"))
    service = RecommendationService(search, tmp_path / "recommendations.json")
    service.save_settings(RecommendationSettings(topics=["transformer", "retrieval"], sources=sources or ["arxiv"], count=5))
    return service


async def test_persist_history_cross_source_dedup_and_multiple_topics(tmp_path):
    daily = service(tmp_path, ["arxiv", "huggingface"])
    daily.start()
    with pytest.raises(SourceError, match="已有推荐"):
        daily.start()
    await daily.runner
    first = daily.state.runs[-1]
    assert first.status == "success" and len(first.papers) == 1
    assert first.papers[0]["topics"] == ["transformer", "retrieval"]
    assert len(first.papers[0]["evidence"]) == 2
    restored = RecommendationService(daily.search, daily.path)
    assert restored.state.runs[0].papers == first.papers
    restored.save_settings(RecommendationSettings(topics=["new topic"], sources=["openalex"]))
    restored.start()
    await restored.runner
    assert restored.state.runs[-1].status == "empty"
    assert restored.state.runs[-1].excluded_count == 1


async def test_failure_excludes_cached_records_and_partial_does_not_lose_success(tmp_path):
    daily = service(tmp_path, ["arxiv", "openalex"])
    daily.search.providers.failing = {"arxiv"}
    today = datetime.now(BEIJING).date()
    query = SearchRequest(query="transformer", sources=["arxiv", "openalex"], start_date=today-timedelta(days=29), end_date=today, limit=50)
    daily.search.cache.write("arxiv", query, SourceData(records=[Record(source="arxiv", source_id="old", title="Old cached only", url="https://example.org", retrieved_at=now())], retrieved_at=now()))
    daily.start()
    await daily.runner
    assert daily.state.runs[-1].status == "partial"
    assert daily.state.runs[-1].papers[0]["sources"] == ["openalex"]
    assert all(not e["cached"] for p in daily.state.runs[-1].candidates for e in p["evidence"])
    daily.search.providers.failing = {"arxiv", "openalex"}
    daily.start()
    await daily.runner
    assert daily.state.runs[-1].status == "failed" and not daily.state.runs[-1].papers


async def test_schedule_due_once_per_day_after_restart_and_only_today(tmp_path):
    daily = service(tmp_path)
    daily.save_settings(daily.state.settings.model_copy(update={"enabled": True}))
    early = datetime(2026, 10, 18, 8, 59, tzinfo=BEIJING)
    await daily.tick(early)
    assert not daily.state.runs
    late = early.replace(hour=23)
    await daily.tick(late)
    await daily.runner
    assert len(daily.state.runs) == 1 and daily.state.runs[0].date == "2026-10-18"
    restored = RecommendationService(daily.search, daily.path)
    await restored.tick(late)
    assert len(restored.state.runs) == 1
    await restored.tick(late + timedelta(days=4))
    await restored.runner
    assert [r.date for r in restored.state.runs] == ["2026-10-18", "2026-10-22"]


async def test_manual_run_satisfies_today_and_disabled_never_schedules(tmp_path):
    daily = service(tmp_path)
    late = datetime(2026, 10, 18, 20, 0, tzinfo=BEIJING)
    await daily.tick(late)
    assert not daily.state.runs
    daily.start(current=late)
    await daily.runner
    daily.save_settings(daily.state.settings.model_copy(update={"enabled": True}))
    await daily.tick(late)
    assert len(daily.state.runs) == 1


async def test_exclusion_filters_title_and_leaves_unrecommended_candidates_eligible(tmp_path):
    daily = service(tmp_path)
    daily.save_settings(daily.state.settings.model_copy(update={"exclude_keywords": ["transformer"]}))
    daily.start()
    await daily.runner
    assert daily.state.runs[-1].status == "empty"
    assert daily.state.runs[-1].keyword_excluded_count == 1
    daily.save_settings(daily.state.settings.model_copy(update={"exclude_keywords": []}))
    daily.start()
    await daily.runner
    assert daily.state.runs[-1].status == "success" and len(daily.state.runs[-1].papers) == 1


async def test_interruption_recovery_and_config_edit_during_run(tmp_path):
    daily = service(tmp_path)
    daily.start()
    # Simulate a restart from the durable running reservation.
    restored = RecommendationService(daily.search, daily.path)
    assert restored.state.runs[-1].status == "interrupted"
    daily.save_settings(RecommendationSettings(topics=["changed"], sources=["arxiv"]))
    await daily.runner
    assert daily.state.settings.topics == ["changed"]
    assert daily.state.runs[-1].settings.topics == ["transformer", "retrieval"]


def test_corrupt_storage_preserved_and_write_failure_not_success(tmp_path, monkeypatch):
    path = tmp_path / "broken.json"
    path.write_text("broken", encoding="utf-8")
    daily = RecommendationService(None, path)
    with pytest.raises(SourceError):
        daily.save_settings(RecommendationSettings())
    assert path.read_text(encoding="utf-8") == "broken"
    good = service(tmp_path)
    old = good.path.read_bytes()
    def fail(*args):
        raise OSError("disk failure")
    monkeypatch.setattr("backend.recommendations.os.replace", fail)
    with pytest.raises(OSError):
        good.save_settings(RecommendationSettings(topics=["new"]))
    assert good.path.read_bytes() == old and good.storage_error


def test_configuration_and_local_api():
    with pytest.raises(ValidationError):
        RecommendationSettings(enabled=True)
    with pytest.raises(ValidationError):
        RecommendationSettings(time="25:00")
    with TestClient(app) as client:
        assert client.get("/api/recommendations").json()["settings"]["enabled"] is False
        assert client.post("/api/recommendations/runs").status_code == 400
        assert client.put("/api/recommendations/settings", json={"topics": ["test"], "enabled": True}, headers={"Origin": "https://example.org"}).status_code == 403
        assert client.put("/api/recommendations/settings", json={"enabled": True}).status_code == 422
        assert client.put("/api/recommendations/settings", json={"topics": ["test"], "time": "20:00"}).status_code == 200
        assert client.get("/api/recommendations/runs/none").status_code == 404

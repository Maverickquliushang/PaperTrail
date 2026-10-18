import importlib

from fastapi.testclient import TestClient

from backend.app import app
from backend.models import Record, SourceData, now
from backend.recommendations import RecommendationService, RecommendationSettings, RecommendationState


class WorkspaceProviders:
    def __init__(self):
        self.called = []

    async def search(self, source, request):
        self.called.append(source)
        return SourceData(records=[Record(source=source, source_id="same", title="Model compression",
            doi="10.1000/shared", url="https://example.org/paper", publication_date=str(request.end_date),
            submitted_date=str(request.end_date), retrieved_at=now())], retrieved_at=now())


def test_workspace_api_binds_source_and_isolates_history_and_settings():
    with TestClient(app) as client:
        providers = WorkspaceProviders()
        app.state.search.providers = providers
        for source in ("arxiv", "openalex"):
            base = f"/api/recommendations?source={source}"
            original = client.get(base).json()
            assert original["settings"]["sources"] == [source]
            assert original["settings"]["enabled"] is False and original["runs"] == []
            invalid = {"topics": ["model compression"], "sources": ["huggingface"]}
            assert client.put(f"/api/recommendations/settings?source={source}", json=invalid).status_code == 422
            settings = {"topics": ["model compression"], "sources": [source]}
            assert client.put(f"/api/recommendations/settings?source={source}", json=settings).status_code == 200
            created = client.post(f"/api/recommendations/runs?source={source}")
            assert created.status_code == 202
            identifier = created.json()["id"]
            for _ in range(100):
                run = client.get(f"/api/recommendations/runs/{identifier}?source={source}").json()
                if run["status"] != "running":
                    break
            assert run["status"] == "success" and len(run["papers"]) == 1
            assert run["papers"][0]["sources"] == [source]
            assert run["excluded_count"] == 0  # same DOI recommended in another workspace is independent
            other = "openalex" if source == "arxiv" else "arxiv"
            assert client.get(f"/api/recommendations/runs/{identifier}?source={other}").status_code == 404
            assert client.get(f"/api/recommendations/runs/{identifier}").status_code == 404
        assert providers.called == ["arxiv", "openalex"]
        global_state = client.get("/api/recommendations").json()
        assert not global_state["runs"] and global_state["settings"]["topics"] == []
        # Even a contradictory request body cannot query a different source in a workspace.
        response = client.post("/api/searches?source=arxiv", json={"query": "test", "sources": ["openalex"]})
        assert response.json()["request"]["sources"] == ["arxiv"]
        assert client.get("/api/recommendations?source=invalid").status_code == 422
        assert client.post("/api/searches?source=invalid", json={"query": "test"}).status_code == 422
        arxiv_path = app.state.source_recommendations["arxiv"].path
        global_path = app.state.recommendations.path
        assert arxiv_path != global_path
    restored = RecommendationService(None, arxiv_path, source="arxiv")
    assert restored.state.settings.sources == ["arxiv"]
    assert len(restored.state.runs) == 1 and restored.state.runs[0].papers[0]["sources"] == ["arxiv"]


def test_source_defaults_copy_existing_preferences_without_migrating_or_enabling():
    module = importlib.import_module("backend.app")
    state = RecommendationState(settings=RecommendationSettings(topics=["existing topic"], time="20:00", count=7, exclude_keywords=["unrelated"]))
    module.RECOMMENDATIONS_PATH.write_text(state.model_dump_json(), encoding="utf-8")
    original = module.RECOMMENDATIONS_PATH.read_bytes()
    with TestClient(app) as client:
        scoped = client.get("/api/recommendations?source=arxiv").json()
        assert scoped["settings"]["topics"] == ["existing topic"]
        assert scoped["settings"]["time"] == "20:00" and scoped["settings"]["count"] == 7
        assert scoped["settings"]["sources"] == ["arxiv"] and not scoped["settings"]["enabled"]
        settings = scoped["settings"] | {"topics": ["custom arxiv"], "time": "21:00"}
        assert client.put("/api/recommendations/settings?source=arxiv", json=settings).status_code == 200
    assert module.RECOMMENDATIONS_PATH.read_bytes() == original
    with TestClient(app) as client:
        assert client.get("/api/recommendations?source=arxiv").json()["settings"]["topics"] == ["custom arxiv"]
        assert client.get("/api/recommendations?source=openalex").json()["settings"]["topics"] == ["existing topic"]
        assert client.get("/api/recommendations").json()["settings"]["topics"] == ["existing topic"]

import importlib

import pytest


@pytest.fixture(autouse=True)
def isolated_recommendation_storage(tmp_path, monkeypatch):
    # API tests must never start the user's configured schedule or touch their history.
    module = importlib.import_module("backend.app")
    monkeypatch.setattr(module, "RECOMMENDATIONS_PATH", tmp_path / "api-recommendations.json")
    monkeypatch.setattr(module, "FEISHU_CONFIG_PATH", tmp_path / "feishu.json")
    monkeypatch.setattr(module, "FEISHU_STATE_PATH", tmp_path / "feishu-deliveries.json")

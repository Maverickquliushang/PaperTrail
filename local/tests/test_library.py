import importlib
import json
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from backend.library import LibraryService

library_tick = LibraryService.tick  # The API fixture disables the background tick.


def test_local_library_serves_shared_ui_and_separate_state():
    module = importlib.import_module('backend.app')
    with TestClient(module.app) as client:
        assert client.get('/library/').status_code == 200
        assert 'GitHub' in client.get('/library/').text
        assert client.get('/library/data/terms.json').status_code == 200
        assert client.get('/api/library').json()['running'] is False
        # The local service starts with an empty private archive, not the public hosted corpus.
        assert module.app.state.library.path.parent == module.LIBRARY_ROOT / 'data/library'
        assert json.loads(module.app.state.library.path.read_text())['papers'] == []


@pytest.mark.asyncio
async def test_library_update_writes_only_local_root(tmp_path, monkeypatch):
    module = importlib.import_module('backend.library')
    value = {'schema':2,'mode':'ai_latest','papers':[],'history':[],'source_status':{},'conference_sync':{}}
    fake = AsyncMock(return_value=value)
    monkeypatch.setattr(module, 'collect', fake)
    service = module.LibraryService(tmp_path, None)
    await service.update(False)
    assert service.error is None
    assert fake.await_count == 1
    assert json.loads(service.path.read_text())['paper_count'] == 0
    assert service.next_attempt > 0


@pytest.mark.asyncio
async def test_library_resumes_source_backlog_after_daily_refresh(tmp_path):
    module = importlib.import_module('backend.library')
    service = module.LibraryService(tmp_path, None)
    today = str(module.datetime.now(module.BEIJING).date())
    service.path.write_text(json.dumps({
        'updated_at': today, 'history': [{'date': today}],
        'conference_sync': {}, 'source_sync': {'huggingface': {'pending': True}},
    }))
    service.start = Mock()
    await library_tick(service)
    service.start.assert_called_once_with(backfill_only=True)

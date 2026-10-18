import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.feishu import BotSettings, FeishuService, PushSettings, atomic_json
from backend.models import SOURCES, now
from backend.recommendations import BEIJING


def event(text, *, identifier="m1", sender="ou_owner", chat="oc_group", bot="ou_bot"):
    return {"event": {"sender": {"sender_type": "user", "sender_id": {"open_id": sender}}, "message": {
        "message_id": identifier, "chat_id": chat, "chat_type": "group", "message_type": "text", "create_time": str(int(time.time() * 1000)),
        "content": json.dumps({"text": "@_user_0 " + text}), "mentions": [{"key": "@_user_0", "id": {"open_id": bot}}]}}}


def service(tmp_path, client, recs=None):
    bot = FeishuService(client, None, lambda: recs or {}, tmp_path / "config.json", tmp_path / "ledger.json")
    bot.settings = BotSettings(enabled=True, app_id="cli_test", app_secret="test_secret")
    bot.bot_id = "ou_bot"
    return bot


@pytest.mark.asyncio
async def test_pairing_requires_fresh_group_mention_and_only_owner_can_command(tmp_path):
    async with httpx.AsyncClient() as client:
        bot = service(tmp_path, client)
        code = bot.start_pairing()["code"]
        await bot.handle_event(event(f"绑定 {code}", bot="other_bot"))
        assert not bot.settings.chat_id
        await bot.handle_event(event(f"绑定 {code}"))
        assert bot.settings.chat_id == "oc_group" and bot.settings.owner_id == "ou_owner"
        assert not bot.settings.push_enabled and not bot.ledger.deliveries
        handled = []

        async def command(identifier, text):
            handled.append(text)

        bot.command = command
        await bot.handle_event(event("帮助", sender="someone_else"))
        await bot.handle_event(event("帮助", chat="another_group"))
        old = event("帮助")
        old["event"]["message"]["create_time"] = "1"
        await bot.handle_event(old)
        await bot.handle_event(event("帮助"))
        await bot.handle_event(event("帮助"))
        await asyncio.gather(*bot.jobs)
        assert handled == ["帮助"]
        restarted = FeishuService(client, None, lambda: {}, bot.config_path, bot.state_path)
        assert restarted.settings.chat_id == "oc_group"
        restarted.bot_id = "ou_bot"
        restarted.command = command
        await restarted.handle_event(event("帮助"))
        assert not restarted.jobs


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "timeout", "rejected"])
async def test_delivery_persists_and_never_retries_ambiguous_sends(tmp_path, outcome):
    sent = []

    def handler(request):
        if "tenant_access_token" in request.url.path:
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "token", "expire": 7200})
        sent.append(json.loads(request.content))
        if outcome == "timeout":
            raise httpx.ReadTimeout("ambiguous", request=request)
        return httpx.Response(200, json={"code": 0, "data": {"message_id": "om_confirmed"}} if outcome == "success" else {"code": 230001})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        bot = service(tmp_path, client)
        bot.settings.chat_id, bot.settings.owner_id = "oc_group", "ou_owner"
        atomic_json(bot.config_path, bot.settings)
        await bot.send("daily:arxiv:date", "PaperTrail · arXiv 推荐")
        await bot.send("daily:arxiv:date", "PaperTrail · arXiv 推荐")
        restarted = FeishuService(client, None, lambda: {}, bot.config_path, bot.state_path)
        await restarted.send("daily:arxiv:date", "PaperTrail · arXiv 推荐")
        assert len(sent) == 1 and sent[0]["receive_id"] == "oc_group"
        assert next(iter(restarted.ledger.deliveries.values()))["status"] == {"success": "sent", "timeout": "unknown", "rejected": "failed"}[outcome]
        assert "test_secret" not in json.dumps(restarted.overview())


@pytest.mark.asyncio
async def test_push_only_new_scheduled_runs_and_all_five_scopes(tmp_path):
    current = datetime.now(timezone.utc)
    recs = {}
    for source in SOURCES:
        old = SimpleNamespace(date=str(current.astimezone(BEIJING).date()), trigger="scheduled", status="success", started_at=(current - timedelta(minutes=2)).astimezone(BEIJING).isoformat(), papers=[], note="old")
        recs[source] = SimpleNamespace(state=SimpleNamespace(runs=[old]))
    async with httpx.AsyncClient() as client:
        bot = service(tmp_path, client, recs)
        bot.settings.chat_id, bot.settings.owner_id = "oc_group", "ou_owner"
        bot.save_push(PushSettings(enabled=True, sources=list(SOURCES)))
        sent = []

        async def send(key, text):
            sent.append((key, text))

        bot.send = send
        await bot.push_ready()
        assert not sent  # includes an explicit UTC versus Beijing timezone comparison
        for source in SOURCES:
            recs[source].state.runs.append(SimpleNamespace(date=str(current.astimezone(BEIJING).date()), trigger="scheduled", status="empty", started_at=now(), papers=[], note="new"))
        await bot.push_ready()
        assert len(sent) == 5
        bot.save_push(PushSettings(enabled=False, sources=list(SOURCES)))
        await bot.push_ready()
        assert len(sent) == 5


def test_status_does_not_expose_credentials_and_push_needs_pairing():
    with TestClient(app) as client:
        data = client.get("/api/feishu").json()
        assert not data["configured"] and "app_secret" not in data
        assert client.post("/api/feishu/pairing").status_code == 400
        assert client.put("/api/feishu/push", json={"enabled": True, "sources": ["arxiv"]}).status_code == 400
        assert client.put("/api/feishu/credentials", json={"app_id": "bad", "app_secret": "secret"}).status_code == 422


@pytest.mark.asyncio
async def test_corrupt_ledger_stops_sending_without_overwriting(tmp_path):
    state_path = tmp_path / "ledger.json"
    state_path.write_text("invalid", encoding="utf-8")
    async with httpx.AsyncClient() as client:
        bot = service(tmp_path, client)
        with pytest.raises(ValueError):
            await bot.send("test", "test")
        assert state_path.read_text() == "invalid"


@pytest.mark.asyncio
async def test_group_search_reuses_search_service_and_replies_with_source_results(tmp_path):
    requests, replies = [], []

    class Search:
        def create(self, request):
            requests.append(request)
            return SimpleNamespace(runner=asyncio.create_task(asyncio.sleep(0)), done=True,
                snapshot=lambda: {"papers": [], "sources": [{"source": "arxiv", "state": "error"}]})

    async with httpx.AsyncClient() as client:
        bot = service(tmp_path, client)
        bot.search = Search()

        async def send(key, text):
            replies.append(text)

        bot.send = send
        await bot.command("id", "检索 arxiv low rank decomposition")
        assert requests[0].sources == ["arxiv"] and requests[0].query == "low rank decomposition"
        assert len(replies) == 2 and "已开始检索" in replies[0] and "arXiv：检索失败" in replies[1]


@pytest.mark.asyncio
async def test_registration_consumes_credentials_without_exposing_them(tmp_path, monkeypatch):
    stream = asyncio.StreamReader()
    stream.feed_data((json.dumps({"authorization_url": "https://accounts.feishu.cn/example"}) + "\n").encode())
    stream.feed_data((json.dumps({"credentials": {"app_id": "cli_created", "app_secret": "private_secret"}}) + "\n").encode())
    stream.feed_eof()
    process = SimpleNamespace(stdout=stream, returncode=0)

    async def spawn(*args, **kwargs):
        assert args[-1] == "--register"
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    async with httpx.AsyncClient() as client:
        bot = FeishuService(client, None, lambda: {}, tmp_path / "config.json", tmp_path / "ledger.json")
        monkeypatch.setattr(bot, "start_listener", lambda: None)
        await bot.register()
        assert bot.settings.app_id == "cli_created"
        assert bot.settings.app_secret == "private_secret"
        assert "private_secret" not in json.dumps(bot.overview()) and not bot.authorization_url
        assert not bot.settings.push_enabled and not bot.settings.chat_id

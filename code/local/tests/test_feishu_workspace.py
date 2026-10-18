import asyncio
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from backend.feishu import BotSettings, FeishuService, paper_text
from backend.feishu_workspace import View, search_request
from backend.models import Record, SOURCES, SourceData, now
from backend.recommendations import BEIJING, RecommendationService, RecommendationSettings
from backend.search import Cache, SearchService


class Providers:
    def __init__(self):
        self.requests = []
        self.gate = None

    async def search(self, source, request):
        self.requests.append(request)
        if self.gate:
            await self.gate.wait()
        return SourceData(records=[Record(source=source, source_id=str(i), title=f"Compression Paper {i}",
            authors=["A. Author"], abstract="Full abstract " * 600, doi=f"10.1234/{i}",
            url=f"https://example.org/{i}", pdf_url=f"https://example.org/{i}.pdf", rank=i,
            submitted_date=f"2026-10-{i:02d}", publication_date=f"2026-10-{i:02d}", retrieved_at=now())
            for i in range(1, min(23, request.limit) + 1)], total=90, scanned=50, limited=True,
            note="有限候选覆盖", retrieved_at=now())


@pytest.fixture
def workspace(tmp_path):
    search = SearchService(Providers(), Cache(tmp_path / "cache"))
    recs = {name: RecommendationService(search, tmp_path / f"{name}.json", source=None if name == "all" else name)
            for name in ["all", *SOURCES]}
    bot = FeishuService(None, search, lambda: recs, tmp_path / "bot.json", tmp_path / "ledger.json")
    bot.settings = BotSettings(enabled=True, app_id="cli_test", app_secret="test_secret", chat_id="oc_group", owner_id="ou_owner")
    bot.bot_id = "ou_bot"
    bot.replies = []

    async def send(key, text):
        bot.replies.append((key, text))

    bot.send = send
    return bot


def response(bot):
    return "".join(text for _, text in bot.replies)


def event(text, identifier, sender="ou_owner"):
    import time
    return {"event": {"sender": {"sender_type": "user", "sender_id": {"open_id": sender}}, "message": {
        "message_id": identifier, "chat_id": "oc_group", "chat_type": "group", "message_type": "text",
        "create_time": str(int(time.time() * 1000)), "content": json.dumps({"text": "@bot " + text}),
        "mentions": [{"key": "@bot", "id": {"open_id": "ou_bot"}}]}}}


def test_search_filters_and_validation():
    request = search_request("检索 arxiv,openreview,hf compression | 最近=30 | 数量=50 | 排序=最新 | 会议=iclr,neurips")
    assert request.sources == ["arxiv", "openreview", "huggingface"]
    assert request.conferences == ["ICLR", "NeurIPS"] and request.limit == 50 and request.sort == "date"
    assert request.end_date == datetime.now(BEIJING).date()
    assert request.start_date == request.end_date - timedelta(days=29)
    assert search_request("检索 all pruning").sources == list(SOURCES)
    assert search_request("检索 all pruning").sort == "date"
    assert search_request("检索 all pruning | 排序=相关性").sort == "relevance"
    for options in ["数量=51", "开始=2026-02-01 | 结束=2026-01-01", "最近=1 | 开始=2026-01-01",
                    "排序=最早", "会议=invalid", "数量=1 | 数量 =2", "未知=1", "最近=0"]:
        with pytest.raises(ValueError):
            search_request("检索 arxiv pruning | " + options)


async def test_pagination_sort_details_status_and_old_results(workspace):
    bot = workspace
    await bot.command("search", "检索 arxiv compression | 数量=50")
    view_id = bot.workspace.latest
    assert "合并去重后共 23 篇" in response(bot) and "第 1 页，共 3 页" in response(bot)
    assert "当前排序：日期从新到旧" in response(bot)
    assert bot.search.providers.requests[-1].sort == "date"
    assert "1. Compression Paper 23" in response(bot)
    assert "limited" not in response(bot) and "只返回部分候选" in response(bot)
    assert "@PaperTrail 下一页" in response(bot)
    bot.replies.clear()
    await bot.command("page", "列表 3")
    assert "21. Compression Paper 3" in response(bot) and "23. Compression Paper 1" in response(bot)
    await bot.command("second", "检索 openalex other")
    bot.replies.clear()
    await bot.command("sort", f"排序 {view_id} 最新")
    assert "1. Compression Paper 23" in response(bot)
    assert bot.workspace.latest == view_id and bot.workspace.get().page == 1
    bot.replies.clear()
    await bot.command("detail", "详情 1")
    detail = response(bot)
    assert "Full abstract " * 600 in detail and "A. Author" in detail and "https://example.org/23.pdf" in detail
    assert all(len(text) <= 2000 for _, text in bot.replies)
    bot.replies.clear()
    await bot.command("source", "来源")
    assert "有限候选覆盖" in response(bot) and "扫描50篇" in response(bot)
    assert "来源总量90" in response(bot) and "缓存时间" in response(bot)
    await bot.command("last", "列表 3")
    await bot.command("invalid", "下一页")
    assert bot.workspace.get().page == 3 and "最后一页" in response(bot)
    await bot.command("first", "上一页")
    assert bot.workspace.get().page == 2
    await bot.command("title", "排序 标题")
    assert [p["title"] for p in bot.workspace.get().papers()][:3] == [f"Compression Paper {i}" for i in range(1, 4)]
    bot.workspace.get().touched -= 1801
    bot.replies.clear()
    await bot.command("expired", "详情 1")
    assert "已过期" in response(bot)


def test_sort_missing_dates_stays_last():
    papers = [{"title": "C", "date": None, "score": 1}, {"title": "A", "date": "2026-01-01", "score": 2},
              {"title": "B", "date": "2026-02-01", "score": 3}]
    view = View("test", "test", task=SimpleNamespace(snapshot=lambda: {"papers": papers}))
    for order, expected in [("date_desc", "BAC"), ("date_asc", "ABC"), ("rank", "BAC")]:
        view.order = order
        assert "".join(p["title"] for p in view.papers()) == expected
    assert papers[0]["title"] == "C"  # Stored results stay unchanged.


async def test_settings_persist_to_shared_store_and_validation_is_atomic(workspace):
    bot = workspace
    await bot.command("settings", "设置 arxiv | 主题=quantization;pruning;distillation;low rank decomposition | 时间=09:00 | 数量=10 | 自动=开启 | 回溯=60 | 去重=7 | 排除词=survey;image | 会议=ICLR")
    daily = bot.recommendations()["arxiv"]
    restored = RecommendationService(bot.search, daily.path, "arxiv")
    assert restored.state.settings == daily.state.settings
    assert daily.overview()["settings"]["topics"][-1] == "low rank decomposition"
    assert daily.state.settings.enabled and daily.state.settings.lookback_days == 60
    assert not bot.recommendations()["openalex"].state.settings.topics
    before = daily.path.read_bytes()
    for command in ["设置 arxiv | 数量=51", "设置 arxiv | 时间=25:00", "设置 arxiv | 来源=openalex",
                    "设置 arxiv | 主题=-", "设置 arxiv | 未知=1"]:
        await bot.command(command, command)
        assert daily.path.read_bytes() == before
    await bot.command("clear", "设置 arxiv | 排除词=-")
    assert not daily.state.settings.exclude_keywords
    await bot.command("global", "设置 all | 来源=arxiv,openalex | 主题=global")
    assert bot.recommendations()["all"].state.settings.sources == ["arxiv", "openalex"]
    assert daily.state.settings.sources == ["arxiv"]


async def test_manual_generation_shared_history_details_and_scope(workspace):
    bot = workspace
    await bot.command("setup", "设置 arxiv | 主题=compression | 数量=23")
    await bot.command("generate", "生成推荐 arxiv")
    daily = bot.recommendations()["arxiv"]
    run = daily.state.runs[-1]
    assert run.status == "success" and run.trigger == "manual" and len(run.papers) == 23
    restored = RecommendationService(bot.search, daily.path, "arxiv")
    assert restored.state.runs[-1].papers == run.papers
    assert not bot.recommendations()["openalex"].state.runs
    dates = [p["date"] for p in bot.workspace.get().papers()]
    assert dates == sorted(dates, reverse=True)
    assert "当前排序：日期从新到旧" in response(bot)
    bot.replies.clear()
    await bot.command("history", "历史 arxiv")
    assert run.id in response(bot)
    await bot.command("view", f"推荐 arxiv {run.id}")
    bot.replies.clear()
    await bot.command("details", "详情 1")
    assert "推荐分" in response(bot) and "检索匹配主题" in response(bot)
    await bot.command("next", "下一页")
    assert bot.workspace.get().page == 2
    bot.replies.clear()
    await bot.command("wrong", f"推荐 openalex {run.id}")
    assert "没有对应推荐记录" in response(bot)
    # History lookup includes runs beyond the first page and does not cross scopes.
    daily.state.runs += [run.model_copy(update={"id": f"history-{i}"}, deep=True) for i in range(11)]
    bot.replies.clear()
    await bot.command("hpage", "历史 arxiv 2")
    assert "第2/2页" in response(bot) and run.id in response(bot)
    bot.replies.clear()
    await bot.command("ambiguous", f"推荐 arxiv {run.date}")
    assert "多条记录" in response(bot)


async def test_long_tasks_allow_cancel_and_global_generation_lock(workspace):
    bot = workspace
    bot.search.providers.gate = asyncio.Event()
    try:
        await bot.handle_event(event("检索 arxiv compression", "s1"))
        await bot.handle_event(event("检索 openalex compression", "s2"))
        await asyncio.sleep(0)
        assert len(bot.long_jobs) == 2
        first = next(iter(bot.workspace.views))
        await bot.handle_event(event("检索 all compression", "s3"))
        assert "任务较多" in response(bot)
        await bot.handle_event(event(f"取消检索 {first}", "cancel"))
        short_jobs = bot.jobs - bot.long_jobs
        await asyncio.gather(*short_jobs)
        assert bot.workspace.views[first].task.done
        assert "检索已取消" in response(bot)
    finally:
        await bot.stop_listener()
        await bot.search.close()
    bot.stopping = False
    await bot.command("setup", "设置 arxiv | 主题=compression")
    daily = bot.recommendations()["arxiv"]
    daily.start()
    try:
        await bot.command("busy", "生成推荐 openalex")
        assert "已有推荐正在生成" in response(bot)
        assert not bot.recommendations()["openalex"].state.runs
    finally:
        await daily.close()


async def test_settings_and_push_require_owner_and_events_are_deduplicated(workspace):
    bot = workspace
    await bot.handle_event(event("设置 arxiv | 主题=compression", "denied", sender="other"))
    assert not bot.jobs and not bot.recommendations()["arxiv"].path.exists()
    await bot.handle_event(event("设置 arxiv | 主题=compression", "ok"))
    await asyncio.gather(*bot.jobs)
    before = len(bot.replies)
    await bot.handle_event(event("设置 arxiv | 主题=wrong", "ok"))
    assert len(bot.replies) == before
    assert bot.recommendations()["arxiv"].state.settings.topics == ["compression"]
    await bot.command("pushsources", "推送 来源=arxiv,openreview")
    assert bot.settings.push_sources == ["arxiv", "openreview"] and not bot.settings.push_enabled
    await bot.command("on", "推送 开启")
    assert bot.settings.push_enabled
    since = bot.settings.push_since
    await bot.command("again", "推送 开启")
    assert bot.settings.push_since == since
    await bot.command("off", "推送 关闭")
    assert not bot.settings.push_enabled
    await bot.command("state", "状态")
    assert "北京时间" in response(bot) and "test_secret" not in response(bot)


async def test_split_messages_fit_wire_limit_and_keep_content(tmp_path):
    sent = []

    def handler(request):
        if "tenant_access_token" in request.url.path:
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "token", "expire": 7200})
        sent.append(request.content)
        return httpx.Response(200, json={"code": 0, "data": {"message_id": "ok"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        bot = FeishuService(client, None, lambda: {}, tmp_path / "config", tmp_path / "ledger")
        bot.settings = BotSettings(enabled=True, app_id="cli_test", app_secret="test_secret", chat_id="oc_group")
        text = '量化😀\\"\n' * 1500
        await bot.workspace.reply("detail", text)
        assert all(len(body) < 20000 for body in sent)
        assert "".join(json.loads(json.loads(body)["content"])["text"] for body in sent) == text
        count = len(sent)
        await bot.workspace.reply("detail", text)
        assert len(sent) == count


def test_five_page_explanation_and_last_page_actions(workspace):
    papers = [{"title": str(i), "date": "2026-01-01", "sources": ["arxiv"]} for i in range(48)]
    view = View("s123", "test", task=SimpleNamespace(snapshot=lambda: {
        "papers": papers, "done": True, "sources": [{"source": s, "state": "limited"} for s in SOURCES]}))
    result = workspace.workspace.listing(view)
    assert "合并去重后共 48 篇" in result
    assert "正在显示第 1–10 篇（第 1 页，共 5 页）" in result
    assert "limited" not in result and "列表 s123 页码" not in result
    view.page = 5
    result = workspace.workspace.listing(view)
    assert "第 41–48 篇" in result and "@PaperTrail 上一页" in result
    assert "@PaperTrail 下一页" not in result
    assert "@PaperTrail 详情 41" in result


def test_daily_push_sorts_copy_by_display_date():
    papers = [{"title": "Unknown", "date": None}, {"title": "Old", "date": "2005-01-01"},
              {"title": "New", "date": "2026-06-05"}]
    result = paper_text("test", papers)
    assert result.index("1. New") < result.index("2. Old") < result.index("3. Unknown")
    assert [p["title"] for p in papers] == ["Unknown", "Old", "New"]


async def test_explicit_relevance_overrides_date_default(workspace):
    await workspace.command("relevance", "检索 arxiv compression | 排序=相关性")
    assert workspace.search.providers.requests[-1].sort == "relevance"
    assert "当前排序：相关性" in response(workspace)
    assert "1. Compression Paper 1" in response(workspace)


async def test_chinese_message_reaches_shared_search_and_discloses_translation(workspace):
    bot = workspace
    await bot.handle_event(event("检索大模型低秩分解", "chinese"))
    await asyncio.gather(*bot.jobs)
    assert bot.search.providers.requests
    assert all(r.query == "large language model low rank decomposition" for r in bot.search.providers.requests)
    assert bot.search.providers.requests[0].sources == list(SOURCES)
    assert "中文主题已转换为：large language model low rank decomposition" in response(bot)
    before = len(bot.search.providers.requests)
    await bot.handle_event(event("检索大模型低秩分解", "chinese"))
    await bot.handle_event(event("检索大模型量化", "unauthorized", sender="other"))
    assert len(bot.search.providers.requests) == before
    await bot.command("unknown", "检索大模型不要量化")
    assert len(bot.search.providers.requests) == before and "没有发起检索" in response(bot)


async def test_chinese_search_uses_same_concurrency_limit(workspace):
    bot = workspace
    bot.search.providers.gate = asyncio.Event()
    try:
        await bot.handle_event(event("检索大模型量化", "c1"))
        await bot.handle_event(event("帮我找大模型剪枝的论文", "c2"))
        await asyncio.sleep(0)
        assert len(bot.long_jobs) == 2
        await bot.handle_event(event("大模型蒸馏", "c3"))
        assert "任务较多" in response(bot) and len(bot.long_jobs) == 2
        await bot.handle_event(event("取消检索", "cancel-c"))
        await asyncio.gather(*(bot.jobs - bot.long_jobs))
        assert "检索已取消" in response(bot)
    finally:
        await bot.stop_listener()
        await bot.search.close()

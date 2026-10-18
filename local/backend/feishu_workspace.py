"""Group interface to the same search tasks and recommendation stores as the web UI."""
from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from pydantic import ValidationError

from .models import CONFERENCES, SOURCES, SearchRequest
from .recommendations import BEIJING, RecommendationSettings
from .sources import SourceError, effective_end_date
from .query_language import english_keywords, search_body, HAN

NAMES = {"arxiv": "arXiv", "openalex": "OpenAlex", "huggingface": "Hugging Face", "conferences": "顶会索引", "openreview": "OpenReview", "all": "综合"}
ALIASES = {**{s: s for s in NAMES}, "综合": "all", "全部": "all", "顶会": "conferences", "顶会索引": "conferences", "hf": "huggingface"}
ORDERS = {"相关性": "rank", "推荐分": "rank", "推荐": "rank", "最新": "date_desc", "最早": "date_asc", "标题": "title"}
SOURCE_STATES = {"pending": "等待检索", "running": "检索中", "success": "检索成功", "limited": "已返回部分候选", "error": "检索失败", "cancelled": "已取消"}
RUN_STATES = {"running": "生成中", "success": "已完成", "partial": "部分来源失败", "empty": "暂无新推荐", "failed": "生成失败", "interrupted": "已中断"}
HELP = """PaperTrail · 群聊工作台（先 @机器人）
直接说：检索图神经网络
也可以说：帮我找计算机视觉的论文
默认搜索全部来源，常见中文研究术语自动转为英文关键词，按日期从新到旧展示。
检索 all graph neural network | 最近=30 | 数量=20 | 排序=最新
检索 arxiv,openreview computer vision | 开始=2026-01-01 | 会议=ICLR,ICML
列表 / 下一页 / 上一页 / 排序 最新 / 详情 1 / 来源 / 取消检索
推荐 arxiv：查看最新记录
历史 arxiv：列出历史；推荐 arxiv 记录ID：查看指定记录
生成推荐 arxiv：立即生成，结果同步网页
设置 arxiv：查看设置；帮助 设置：完整修改方法
推送：查看；推送 开启 / 推送 关闭 / 推送 来源=arxiv,openreview
状态：查看任务和各专区计划；网页：本机入口
来源：arxiv / openalex / huggingface（hf）/ conferences（顶会）/ openreview / all（综合）
每页10篇，全部结果可翻页。列表带结果ID，可用“详情 结果ID 1”“排序 结果ID 最新”“列表 结果ID 2”“来源 结果ID”查看旧结果。
帮助 检索 / 帮助 推荐 / 帮助 设置 可查看完整语法。"""
SEARCH_HELP = """直接发送：检索图神经网络（空格可有可无）
默认全部来源；计算机视觉、自然语言处理、图神经网络等常见中文术语自动转为英文关键词。
回复会显示实际关键词；不认识的中文会提示，不会偷偷删掉后继续搜索。
可选：检索 <来源或逗号分隔的多个来源> <中文主题或英文关键词> | 参数=值
例如：检索 arxiv,openreview graph neural network | 最近=30 | 数量=20 | 排序=最新 | 会议=ICLR,ICML
参数：开始=YYYY-MM-DD、结束=YYYY-MM-DD、最近=天数（含今天）、数量=1～50（每个来源）、排序=相关性/最新、会议=会议名列表。
最近不能与开始/结束同时使用。会议：""" + ", ".join(CONFERENCES) + """
默认按日期从新到旧取数和展示；填写“排序=相关性”可按相关性检索。“排序 最新/最早/标题/相关性”只重排当前结果，不重新请求。
用“列表”查看检索中的部分结果；“取消检索 [结果ID]”仅取消在本群发起的检索。
检索截止不晚于今天，未来发表日期不展示。OpenAlex/顶会索引只匹配标题和摘要；Hugging Face 仅在有限候选中筛选。
可组合多个研究关键词缩小范围；关键词命中不代表语义理解。"""
SETTINGS_HELP = """设置 <专区>：查看当前设置
设置 arxiv | 主题=computer vision;graph neural network | 时间=09:00 | 数量=10
可修改：主题（分号分隔，最多5个）、排除词（分号分隔，清空用“-”）、时间（北京时间HH:MM）、数量（1～50）、回溯（1～365天）、去重（1～365天）、自动=开启/关闭、会议=ICLR,ICML、来源=arxiv,openalex。
“来源”仅综合（all）可以修改，专区始终固定自己的来源。修改立即保存并同步网页。
设置 all 表示综合工作台，不代表批量修改五个专区。
自动生成与飞书推送是独立开关；推送只处理开启后新产生的当天定时推荐。"""
RECOMMEND_HELP = """推荐 <专区>：查看该专区最新记录（含运行状态）
历史 <专区> [页码]：每页10条历史，包含记录ID
推荐 <专区> <记录ID或日期>：查看历史，同一天多次生成请使用记录ID
生成推荐 <专区>：复用网页的立即生成；各专区共用生成队列，同一时间只生成一份
生成开始后可用“状态”或“推荐 专区”查看进度。
推荐结果默认按日期从新到旧展示，支持列表翻页、详情、来源、排序 最新/最早/标题/推荐分；排序不会改写历史或改变推荐候选。
群里手动生成会返回结果，不自动推送其他历史记录。"""


def scope(text: str) -> str:
    value = ALIASES.get(text.lower())
    if not value:
        raise ValueError("来源无效。可用：" + ", ".join(NAMES))
    return value


def sources(text: str) -> list[str]:
    result = []
    for item in re.split(r"[,，、]", text):
        value = scope(item.strip())
        result.extend(SOURCES if value == "all" else [value])
    return list(dict.fromkeys(result))


def conferences(text: str) -> list[str]:
    lookup = {c.lower(): c for c in CONFERENCES}
    try:
        return list(dict.fromkeys(lookup[c.strip().lower()] for c in re.split(r"[,，、]", text)))
    except KeyError:
        raise ValueError("会议名称无效。可用：" + ", ".join(CONFERENCES)) from None


def options(text: str) -> tuple[str, dict[str, str]]:
    chunks = re.split(r"[|｜]", text)
    result = {}
    for chunk in chunks[1:]:
        key, separator, value = chunk.strip().partition("=")
        key = key.strip()
        if not separator or not key or not value.strip() or key in result:
            raise ValueError("参数请用“| 参数=值”，参数不能重复或为空。")
        result[key.strip()] = value.strip()
    return chunks[0].strip(), result


def search_request(text: str) -> SearchRequest:
    head, opts = options(text)
    body = search_body(head)
    if not body:
        raise ValueError(SEARCH_HELP)
    chosen = list(SOURCES)
    parts = body.split(maxsplit=1)
    source_parts = re.split(r"[,，、]", parts[0])
    if any(part.lower() in ALIASES for part in source_parts):
        chosen = sources(parts[0])
        if len(parts) != 2:
            raise ValueError("请告诉我研究主题，例如“检索图神经网络”或“检索 arxiv 计算机视觉”。")
        body = parts[1]
    unknown = set(opts) - {"开始", "结束", "最近", "数量", "排序", "会议"}
    if unknown:
        raise ValueError("未知检索参数：" + "、".join(sorted(unknown)))
    data = {"query": english_keywords(body), "sources": chosen, "limit": opts.get("数量", 10)}
    if "最近" in opts:
        if "开始" in opts or "结束" in opts:
            raise ValueError("最近天数与开始/结束日期不能同时使用。")
        days = int(opts["最近"])
        if not 1 <= days <= 3650:
            raise ValueError("最近天数须为1～3650。")
        today = datetime.now(BEIJING).date()
        data.update(start_date=today - timedelta(days=days - 1), end_date=today)
    else:
        data.update(start_date=opts.get("开始"), end_date=opts.get("结束"))
    order = opts.get("排序", "最新")
    if order not in ("相关性", "最新"):
        raise ValueError("检索取数排序可用：相关性、最新。结果列表另支持最早、标题。")
    data["sort"] = "date" if order == "最新" else "relevance"
    if "会议" in opts:
        data["conferences"] = conferences(opts["会议"])
    return SearchRequest.model_validate(data)


def by_date(items, descending=True):
    """Sort a copy by the same displayed date, keeping unknown dates last."""
    def valid_date(p):
        try:
            return date.fromisoformat((p.get("date") or "")[:10])
        except ValueError:
            return None
    dated = [p for p in items if valid_date(p)]
    return sorted(dated, key=valid_date, reverse=descending) + [p for p in items if not valid_date(p)]


@dataclass
class View:
    id: str
    title: str
    task: object = None
    service: object = None
    run_id: str = ""
    order: str = "date_desc"
    page: int = 1
    touched: float = field(default_factory=time.monotonic)

    def snapshot(self):
        if self.task:
            return self.task.snapshot()
        run = next((r for r in self.service.state.runs if r.id == self.run_id), None)
        if not run:
            raise ValueError("推荐记录不存在，请重新查看历史。")
        return run.model_dump(exclude={"candidates"})

    def papers(self):
        items = list(self.snapshot()["papers"])
        if self.order == "rank":
            key = "recommendation_score" if self.service else "score"
            return sorted(items, key=lambda p: p.get(key, float("-inf")), reverse=True)
        if self.order == "title":
            return sorted(items, key=lambda p: [int(v) if v.isdigit() else v for v in re.split(r"(\d+)", p["title"].casefold())])
        return by_date(items, descending=self.order == "date_desc")


class GroupWorkspace:
    def __init__(self, bot):
        self.bot = bot
        self.views: dict[str, View] = {}
        self.latest = ""

    def remember(self, view):
        self.views = {k: v for k, v in self.views.items() if time.monotonic() - v.touched < 1800 or (v.task and not v.task.done)}
        while len(self.views) >= 20:
            removable = next((k for k, v in self.views.items() if not v.task or v.task.done), None)
            if removable is None:
                break
            del self.views[removable]
        self.views[view.id] = view
        self.latest = view.id
        return view

    def get(self, identifier=""):
        view = self.views.get(identifier or self.latest)
        if not view or (time.monotonic() - view.touched > 1800 and (not view.task or view.task.done)):
            raise ValueError("结果不存在或已过期（30分钟）。请重新检索，或用“推荐 专区 记录ID”重新打开历史。")
        view.touched = time.monotonic()
        self.latest = view.id
        return view

    async def reply(self, key, text):
        # Stay below Feishu's byte limit, including nested JSON escaping of Chinese text.
        for index, offset in enumerate(range(0, len(text), 2000)):
            await self.bot.send(f"{key}:{index}", text[offset:offset + 2000])

    def listing(self, view):
        data, papers = view.snapshot(), view.papers()
        pages = max(1, (len(papers) + 9) // 10)
        if not 1 <= view.page <= pages:
            raise ValueError(f"页码须在1～{pages}之间。")
        state = RUN_STATES.get(data.get("status"), "已完成" if data.get("done", True) else "检索中")
        order = {"date_desc": "日期从新到旧", "date_asc": "日期从旧到新", "title": "标题", "rank": "推荐分" if view.service else "相关性"}[view.order]
        start, end = (view.page - 1) * 10 + 1, min(view.page * 10, len(papers))
        total = f"本次推荐共 {len(papers)} 篇" if view.service else f"本次检索合并去重后共 {len(papers)} 篇"
        pagination = f"正在显示第 {start}–{end} 篇（第 {view.page} 页，共 {pages} 页）" if papers else "暂无论文可展示"
        rows = [f"PaperTrail · {view.title}\n{state} · 当前排序：{order}\n{total}\n{pagination}"]
        if view.order in ("date_desc", "date_asc"):
            rows.append("按下方标注日期排序；arXiv 使用首次提交日期，其他来源使用发表或公开日期。未提供日期的论文放在最后。")
        if data.get("note"):
            rows.append(data["note"])
        if view.service:
            settings = data["settings"]
            rows.append("本次主题：" + "; ".join(settings["topics"])
                        + f"\n回溯{settings['lookback_days']}天 · 去重{settings['dedup_days']}天 · 历史去重排除{data['excluded_count']}篇 · 排除词过滤{data['keyword_excluded_count']}篇")
        if not papers:
            rows.append("暂无可显示论文；请用“来源”查看失败、候选覆盖和缓存状态。")
        for index, paper in enumerate(papers[(view.page - 1) * 10:view.page * 10], (view.page - 1) * 10 + 1):
            link = next((e.get("url", "") for e in paper.get("evidence", []) if e.get("url", "").startswith(("https://", "http://"))), "")
            rows.append(f"{index}. {paper['title']}\n{paper.get('date') or '日期未提供'} · {' / '.join(NAMES[s] for s in paper.get('sources', []))}\n{link}")
        if view.task:
            statuses = data.get("sources", [])
            limited = [NAMES[s["source"]] for s in statuses if s["state"] == "limited"]
            warnings = [f"{NAMES[s['source']]}：{SOURCE_STATES.get(s['state'], '状态未知')}" + ("（保留上次缓存）" if s.get("cached_at") else "")
                        for s in statuses if s["state"] not in ("success", "limited")]
            if limited:
                warnings.append("、".join(limited) + "：只返回部分候选，未覆盖全部匹配论文；这不代表检索失败。")
            if warnings:
                rows.append("\n".join(warnings))
        actions = []
        if view.page < pages:
            actions.append("查看下一页：@PaperTrail 下一页")
        if view.page > 1:
            actions.append("查看上一页：@PaperTrail 上一页")
        if papers:
            actions.append(f"查看第{start}篇摘要和原文：@PaperTrail 详情 {start}")
            actions.append("切换排序：@PaperTrail 排序 " + ("最新" if view.order != "date_desc" else "推荐分" if view.service else "相关性"))
        actions.append("查看来源说明：@PaperTrail 来源")
        rows.append("\n".join(actions))
        return "\n\n".join(rows)

    def settings_text(self, name, service):
        value = service.state.settings
        overview = service.overview()
        return (f"PaperTrail · {NAMES[name]}推荐设置\n主题：" + "; ".join(value.topics)
                + "\n排除词：" + ("; ".join(value.exclude_keywords) or "无")
                + f"\n自动：{'开启' if value.enabled else '关闭'} · 时间：{value.time}（北京时间）\n数量：{value.count} · 回溯：{value.lookback_days}天 · 去重：{value.dedup_days}天"
                + "\n来源：" + ", ".join(value.sources) + "\n会议：" + ", ".join(value.conferences)
                + f"\n生成中：{'是' if overview['running'] else '否'}\n下次检查：{overview['next_run'] or '未安排'}"
                + ("\n存储异常，请查看本地网页。" if overview['storage_error'] else "")
                + "\n修改方法：帮助 设置")

    async def command(self, identifier, text):
        active = None
        try:
            head, opts = options(text)
            words = head.split()
            if not words:
                raise ValueError(HELP)
            cmd, args = words[0], words[1:]
            if search_body(head) is not None:
                cmd = "检索"
            if opts and cmd not in ("检索", "设置"):
                raise ValueError("此操作不接受“|”参数，请发送“帮助”查看语法。")
            if cmd == "帮助":
                result = {"检索": SEARCH_HELP, "设置": SETTINGS_HELP, "推荐": RECOMMEND_HELP}.get(" ".join(args), HELP)
            elif cmd == "检索":
                request = search_request(text)
                active = self.bot.search.create(request)
                view = self.remember(View("s" + getattr(active, "id", uuid.uuid4().hex)[:10], request.query, task=active,
                                          order="date_desc" if request.sort == "date" else "rank"))
                keyword_label = "中文主题已转换为" if HAN.search(search_body(head) or "") else "检索关键词"
                await self.reply(f"ack:{identifier}", f"PaperTrail · 已开始检索 {' / '.join(NAMES[s] for s in request.sources)}\n{keyword_label}：{request.query}\n日期范围：{request.start_date or '不限'} 至 {effective_end_date(request)}；每来源最多{request.limit}篇\n排序：{'日期从新到旧' if request.sort == 'date' else '相关性'}\n需要停止时，@PaperTrail 发送“取消检索”。\n检索编号：{view.id}（查看旧结果时使用）")
                await active.runner
                self.latest = view.id
                result = self.listing(view)
            elif cmd in ("推荐", "历史", "设置", "生成推荐"):
                if not args or len(args) > (2 if cmd in ("推荐", "历史") else 1):
                    raise ValueError("请指定专区，例如：" + cmd + " arxiv。all 表示综合工作台。")
                name = scope(args[0])
                service = self.bot.recommendations()[name]
                if cmd == "设置":
                    if opts:
                        fields = {"主题": "topics", "排除词": "exclude_keywords", "时间": "time", "数量": "count", "回溯": "lookback_days", "去重": "dedup_days", "来源": "sources", "会议": "conferences", "自动": "enabled"}
                        if set(opts) - fields.keys():
                            raise ValueError("未知设置字段。请发送“帮助 设置”。")
                        updated = service.state.settings.model_dump()
                        for key, value in opts.items():
                            if key in ("主题", "排除词"):
                                value = [] if value == "-" else [v.strip() for v in re.split(r"[;；]", value) if v.strip()]
                            elif key == "来源":
                                value = sources(value)
                            elif key == "会议":
                                value = conferences(value)
                            elif key == "自动":
                                if value not in ("开启", "关闭"):
                                    raise ValueError("自动只能设置为开启或关闭。")
                                value = value == "开启"
                            updated[fields[key]] = value
                        service.save_settings(RecommendationSettings.model_validate(updated))
                    result = ("设置已保存，与网页同步。\n" if opts else "") + self.settings_text(name, service)
                elif cmd == "历史":
                    page = int(args[1]) if len(args) == 2 else 1
                    runs = list(reversed(service.state.runs))
                    pages = max(1, (len(runs) + 9) // 10)
                    if not 1 <= page <= pages:
                        raise ValueError(f"历史页码须在1～{pages}之间。")
                    result = f"PaperTrail · {NAMES[name]}推荐历史 第{page}/{pages}页\n" + "\n".join(f"{r.date} {r.started_at[11:19]} · {RUN_STATES[r.status]} · {len(r.papers)}篇 · {'手动生成' if r.trigger == 'manual' else '定时生成'}\n记录ID：{r.id}" for r in runs[(page - 1) * 10:page * 10])
                    result += f"\n查看：推荐 {name} 记录ID\n翻页：历史 {name} 页码" if runs else "暂无推荐记录。"
                else:
                    if cmd == "生成推荐":
                        if any(s.runner and not s.runner.done() for s in self.bot.recommendations().values()):
                            raise ValueError("已有推荐正在生成（可能来自其他专区），请完成后再试。")
                        run = service.start()
                        await self.reply(f"ack:{identifier}", f"PaperTrail · 已开始生成{NAMES[name]}推荐，结果同步网页。\n记录ID：{run.id}\n可发送“状态”查看进度。")
                    else:
                        target = args[1] if len(args) == 2 else ""
                        matches = [r for r in service.state.runs if not target or r.id == target or r.date == target]
                        if not matches:
                            raise ValueError("此专区没有对应推荐记录。请查看“历史 专区”，或发送“生成推荐 专区”。")
                        if target and len(matches) > 1:
                            raise ValueError("该日期有多条记录，请用“历史 专区”中的完整记录ID选择。")
                        run = matches[-1]
                    view = self.remember(View("r" + run.id[:10], f"{NAMES[name]} 推荐 · {run.date}", service=service, run_id=run.id))
                    if cmd == "生成推荐":
                        await asyncio.shield(service.runner)
                        service.guard()
                    self.latest = view.id
                    result = self.listing(view)
            elif cmd in ("列表", "下一页", "上一页", "排序", "详情", "来源", "取消检索"):
                view = self.get(args.pop(0) if args and args[0] in self.views else "")
                if cmd == "取消检索":
                    if args or not view.task:
                        raise ValueError("请指定本群发起的检索结果ID。推荐生成不支持此取消操作。")
                    await self.bot.search.cancel(view.task)
                    result = "检索已取消，已返回的结果保留。\n" + self.listing(view)
                elif cmd == "来源":
                    if args:
                        raise ValueError("用法：来源 [结果ID]")
                    data = view.snapshot()
                    rows = data.get("source_results", [{"sources": data.get("sources", [])}])
                    result = f"PaperTrail · {view.title} · 来源状态\n" + "\n\n".join(
                        (f"主题：{row['topic']}\n" if row.get("topic") else "") + (row.get("error") or "") + "\n".join(
                            f"{NAMES[s['source']]}：{SOURCE_STATES.get(s['state'], '状态未知')} · 返回{s.get('count', 0)}篇 · 扫描{s.get('scanned', 0)}篇 · 来源总量{s.get('total') if s.get('total') is not None else '未知'}\n{s.get('note', '')}\n检索时间：{s.get('retrieved_at') or '未返回'}；缓存时间：{s.get('cached_at') or '无'}"
                            for s in row.get("sources", [])) for row in rows)
                elif cmd == "详情":
                    if len(args) != 1:
                        raise ValueError("用法：详情 [结果ID] 论文序号")
                    number = int(args[0])
                    papers = view.papers()
                    if not 1 <= number <= len(papers):
                        raise ValueError("论文序号超出当前结果范围。")
                    p = papers[number - 1]
                    result = f"PaperTrail · 结果{view.id} 第{number}篇\n{p['title']}\n作者：" + " / ".join(p.get("authors", []))
                    result += f"\n日期：{p.get('date') or '未提供'}（{p.get('date_kind') or '来源日期'}）\nDOI：{p.get('doi') or '无'}\narXiv：{p.get('arxiv_id') or '无'}\n摘要：\n{p.get('abstract') or '来源未提供摘要'}\n摘要来源：{p.get('abstract_source') or '无'}"
                    if "recommendation_score" in p:
                        result += f"\n推荐分：{p['recommendation_score']}（规则排序，非质量评价）\n" + "\n".join(p.get("reasons", []))
                    for e in p.get("evidence", []):
                        result += f"\n\n{NAMES[e['source']]} · {e.get('venue') or e.get('conference') or '未提供会议信息'}\n原文：{e.get('url') or '无'}\nPDF：{e.get('pdf_url') or '无'}\n首次提交：{e.get('submitted_date') or '无'}；发表：{e.get('publication_date') or '无'}；更新：{e.get('updated_date') or '无'}；收录：{e.get('listed_date') or '无'}\n检索于：{e.get('retrieved_at') or '无'} · {'缓存' if e.get('cached') else '本次获取'}"
                else:
                    if cmd == "排序":
                        if len(args) != 1 or args[0] not in ORDERS:
                            raise ValueError("排序可用：最新、最早、标题、相关性、推荐分。")
                        view.order, view.page = ORDERS[args[0]], 1
                    elif cmd == "列表":
                        if len(args) > 1:
                            raise ValueError("用法：列表 [结果ID] [页码]")
                        page = int(args[0]) if args else view.page
                        if not 1 <= page <= max(1, (len(view.papers()) + 9) // 10):
                            raise ValueError("页码超出范围。")
                        view.page = page
                    else:
                        if args:
                            raise ValueError("翻页只接受可选的结果ID。")
                        page = view.page + (1 if cmd == "下一页" else -1)
                        if not 1 <= page <= max(1, (len(view.papers()) + 9) // 10):
                            raise ValueError("已是第一页或最后一页。")
                        view.page = page
                    result = self.listing(view)
            elif cmd == "推送":
                from .feishu import PushSettings
                if len(args) > 1:
                    raise ValueError("用法：推送 开启/关闭，或 推送 来源=arxiv,openreview")
                if args:
                    value = args[0]
                    if value.startswith("来源="):
                        chosen, enabled = sources(value[3:]), self.bot.settings.push_enabled
                    elif value in ("开启", "关闭"):
                        chosen, enabled = self.bot.settings.push_sources, value == "开启"
                    else:
                        raise ValueError("推送参数无效，请发送“帮助”。")
                    self.bot.save_push(PushSettings(enabled=enabled, sources=chosen))
                result = f"PaperTrail · 每日推送{'已开启' if self.bot.settings.push_enabled else '已关闭'}\n来源：" + ", ".join(self.bot.settings.push_sources) + "\n各专区定时生成完成后发送；不补发旧记录。每区每条推送最多10篇，其余可用推荐和翻页查看。"
            elif cmd == "状态" and not args:
                result = f"PaperTrail · {self.bot.connection}\n每日推送：{'开启' if self.bot.settings.push_enabled else '关闭'}\n" + "\n".join(
                    f"{NAMES[name]}：{'生成中' if s.runner and not s.runner.done() else '空闲'} · 自动{'开启' if s.state.settings.enabled else '关闭'} · {s.state.settings.time} · 最多{s.state.settings.count}篇" for name, s in self.bot.recommendations().items())
                result += "\n群内检索：" + ("、".join(v.id for v in self.views.values() if v.task and not v.task.done) or "无")
                result += "\n时间均为北京时间；电脑及后台需保持运行。"
            elif cmd == "网页" and not args:
                result = "PaperTrail 本机入口：http://127.0.0.1:8000/\n仅运行 PaperTrail 的电脑可打开此地址。账号凭据、绑定和连接管理请在本地网页操作。"
            else:
                result = "暂未识别此操作。当前使用中文指令，不调用豆包模型。\n\n" + HELP
            await self.reply(f"result:{identifier}", result)
        except asyncio.CancelledError:
            if active and not active.done:
                await self.bot.search.cancel(active)
            raise
        except ValidationError as exc:
            fields = ", ".join(".".join(str(v) for v in e["loc"]) for e in exc.errors())
            await self.reply(f"error:{identifier}", f"参数校验失败：{fields}。请查看“帮助 检索”或“帮助 设置”。没有保存本次设置。")
        except SourceError as exc:
            await self.reply(f"error:{identifier}", "操作未完成：" + (exc.message if exc.code != "storage" else "本地存储异常，请查看网页。"))
        except ValueError as exc:
            message = str(exc)
            if message.startswith("invalid literal"):
                message = "数量、天数、页码和论文序号请使用整数。"
            await self.reply(f"error:{identifier}", message)
        except Exception:
            self.bot.error = "群聊请求处理失败；请检查来源状态或本地存储。"
            await self.reply(f"error:{identifier}", "本次操作未完成，请查看本地网页状态后再试。")

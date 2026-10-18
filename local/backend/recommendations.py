from __future__ import annotations

import asyncio
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .models import CONFERENCES, SOURCES, Conference, Record, SearchRequest, Source, now
from .search import SearchService, identities, merge_records
from .sources import SourceError

BEIJING = timezone(timedelta(hours=8), name="Asia/Shanghai")


class RecommendationSettings(BaseModel):
    enabled: bool = False
    topics: list[str] = Field(default_factory=list, max_length=5)
    exclude_keywords: list[str] = Field(default_factory=list, max_length=30)
    time: str = Field(default="09:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    count: int = Field(default=10, ge=1, le=50)
    lookback_days: int = Field(default=30, ge=1, le=365)
    dedup_days: int = Field(default=30, ge=1, le=365)
    sources: list[Source] = Field(default_factory=lambda: list(SOURCES), min_length=1)
    conferences: list[Conference] = Field(default_factory=lambda: list(CONFERENCES), min_length=1)

    @field_validator("topics")
    @classmethod
    def clean_topics(cls, values):
        return list(dict.fromkeys(SearchRequest(query=value).query for value in values))

    @field_validator("exclude_keywords")
    @classmethod
    def clean_exclusions(cls, values):
        values = list(dict.fromkeys(v.strip().lower() for v in values if v.strip()))
        if any(len(v) > 100 for v in values):
            raise ValueError("每个排除词最多 100 个字符")
        return values

    @field_validator("sources", "conferences")
    @classmethod
    def unique(cls, values):
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def configured(self):
        if self.enabled and not self.topics:
            raise ValueError("请先填写研究主题，再开启每日自动推荐")
        return self


class RecommendationRun(BaseModel):
    id: str
    date: str
    trigger: Literal["manual", "scheduled"]
    started_at: str
    finished_at: str | None = None
    status: Literal["running", "success", "partial", "empty", "failed", "interrupted"] = "running"
    settings: RecommendationSettings
    papers: list[dict] = Field(default_factory=list)
    candidates: list[dict] = Field(default_factory=list)
    source_results: list[dict] = Field(default_factory=list)
    excluded_count: int = 0
    keyword_excluded_count: int = 0
    note: str = "正在检索并生成推荐。"


class RecommendationState(BaseModel):
    version: Literal[1] = 1
    settings: RecommendationSettings = Field(default_factory=RecommendationSettings)
    runs: list[RecommendationRun] = Field(default_factory=list)


def paper_keys(paper: dict) -> set[str]:
    return set().union(*(identities(Record.model_validate(e)) for e in paper["evidence"]))


def rank_papers(records: list[Record], topic_keys: dict[str, set[str]], today) -> list[dict]:
    papers = merge_records(records, "relevance")
    for paper in papers:
        keys = paper_keys(paper)
        topics = [topic for topic, found in topic_keys.items() if keys & found]
        tokens = {word.lower() for topic in topics for word in re.findall(r"\w+", topic)}
        title_tokens = set(re.findall(r"\w+", paper["title"].lower()))
        coverage = len(tokens & title_tokens) / max(len(tokens), 1)
        dates = [r.filter_date for r in records if identities(r) & keys and r.filter_date]
        latest = max(dates) if dates else None
        age = max(0, (today - datetime.fromisoformat(latest).date()).days) if latest else 365
        freshness = 1 / (1 + age / 7)
        conference = next((e.get("conference") for e in paper["evidence"] if e.get("conference")), None)
        paper["recommendation_score"] = round(45 * coverage + 25 * min(1, paper["score"] * 61 / 4) + 20 * freshness + (10 if conference else 0), 2)
        paper["topics"] = topics
        paper["reasons"] = ["检索匹配主题：" + "、".join(topics), f"标题关键词覆盖 {coverage:.0%}；结合来源排名和日期排序"]
        if conference:
            paper["reasons"].append(f"会议记录：{conference}（依据来源元数据）")
    papers.sort(key=lambda p: (-p["recommendation_score"], p["id"]))
    return papers


class RecommendationService:
    """Single-process scheduler; atomic state includes both history and settings."""

    def __init__(self, search: SearchService, path: Path, source: Source | None = None,
                 initial_settings: RecommendationSettings | None = None):
        self.search = search
        self.path = path
        self.source = source
        self.state = RecommendationState()
        if initial_settings is not None:
            self.state.settings = initial_settings.model_copy(deep=True)
        if source:
            self.state.settings.sources = [source]
            self.state.settings.enabled = False
        self.storage_error: str | None = None
        self.runner: asyncio.Task | None = None
        self.scheduler: asyncio.Task | None = None
        try:
            self.state = RecommendationState.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            self.storage_error = "推荐数据读取失败，已停止自动生成并保留原文件。请检查 data/recommendations.json。"
        if source and (self.state.settings.sources != [source] or any(r.settings.sources != [source] for r in self.state.runs)):
            self.storage_error = "专区推荐文件包含其他来源，已停止运行，请检查此专区数据。"
        if not self.storage_error and any(r.status == "running" for r in self.state.runs):
            recovered = self.state.model_copy(deep=True)
            for run in recovered.runs:
                if run.status == "running":
                    run.status, run.finished_at = "interrupted", now()
                    run.note = "上次运行被中断，未计入推荐去重；可手动重新生成。"
            try:
                self.commit(recovered)
            except OSError:
                pass

    def commit(self, state: RecommendationState):
        temporary = self.path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("w", encoding="utf-8") as file:
                file.write(state.model_dump_json())
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
            self.state = state
        except OSError:
            self.storage_error = "推荐数据保存失败，已停止自动生成；原有历史保留。请检查磁盘与文件权限后重启。"
            raise
        finally:
            temporary.unlink(missing_ok=True)

    def guard(self):
        if self.storage_error:
            raise SourceError("storage", self.storage_error)

    def save_settings(self, settings: RecommendationSettings):
        self.guard()
        if self.source and settings.sources != [self.source]:
            raise SourceError("scope", "专区只能使用当前论文来源，请返回综合工作台进行多来源推荐。")
        state = self.state.model_copy(deep=True)
        state.settings = settings
        self.commit(state)
        return settings

    def overview(self) -> dict:
        current = datetime.now(BEIJING)
        settings = self.state.settings
        next_run = None
        if settings.enabled and not self.storage_error:
            hour, minute = map(int, settings.time.split(":"))
            due = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if any(r.date == str(current.date()) for r in self.state.runs):
                due += timedelta(days=1)
            next_run = max(due, current).isoformat()
        return {
            "source": self.source,
            "settings": settings.model_dump(), "storage_error": self.storage_error,
            "next_run": next_run, "running": bool(self.runner and not self.runner.done()),
            "runs": [r.model_dump(exclude={"candidates", "papers"}) | {"paper_count": len(r.papers)} for r in reversed(self.state.runs)],
        }

    def start(self, trigger="manual", current: datetime | None = None) -> RecommendationRun:
        self.guard()
        if self.runner and not self.runner.done():
            raise SourceError("busy", "已有推荐正在生成，请等待完成。")
        if not self.state.settings.topics:
            raise SourceError("configuration", "请先保存至少一个研究主题。")
        current = (current or datetime.now(BEIJING)).astimezone(BEIJING)
        run = RecommendationRun(id=uuid.uuid4().hex, date=str(current.date()), trigger=trigger,
                                started_at=current.isoformat(), settings=self.state.settings.model_copy(deep=True))
        state = self.state.model_copy(deep=True)
        state.runs.append(run)
        self.commit(state)
        self.runner = asyncio.create_task(self.generate(run.model_copy(deep=True)))
        return run

    async def generate(self, run: RecommendationRun):
        active = None
        try:
            settings = run.settings
            today = datetime.fromisoformat(run.date).date()
            cutoff = datetime.fromisoformat(run.started_at) - timedelta(days=settings.dedup_days)
            seen = set()
            for previous in self.state.runs:
                if previous.finished_at and datetime.fromisoformat(previous.finished_at) >= cutoff and previous.status in ("success", "partial"):
                    for paper in previous.papers:
                        seen |= paper_keys(paper)
            records, topic_keys = [], {}
            successes = failures = 0
            for topic in settings.topics:
                query = SearchRequest(query=topic, sources=settings.sources, conferences=settings.conferences,
                                      start_date=today - timedelta(days=settings.lookback_days - 1), end_date=today,
                                      limit=50, sort="relevance")
                try:
                    active = self.search.create(query)
                    await active.runner
                    results = list(active.statuses.values())
                    run.source_results.append({"topic": topic, "sources": [s.model_dump() for s in results]})
                    successes += sum(s.state in ("success", "limited") for s in results)
                    failures += sum(s.state not in ("success", "limited") for s in results)
                    fresh = [r for source, values in active.records.items() if active.statuses[source].state in ("success", "limited") for r in values if not r.cached]
                    records.extend(fresh)
                    topic_keys[topic] = set().union(*(identities(r) for r in fresh))
                except SourceError as exc:
                    failures += 1
                    run.source_results.append({"topic": topic, "sources": [], "error": exc.message})
            # A paper returned for several topics should not duplicate its evidence.
            unique = {}
            for record in records:
                key = (record.source, record.source_id)
                if key not in unique or record.rank < unique[key].rank:
                    unique[key] = record
            run.candidates = rank_papers(list(unique.values()), topic_keys, today)
            matching = [p for p in run.candidates if not any(
                keyword in (p["title"] + " " + (p["abstract"] or "")).lower()
                for keyword in settings.exclude_keywords)]
            run.keyword_excluded_count = len(run.candidates) - len(matching)
            available = [p for p in matching if not (paper_keys(p) & seen)]
            run.excluded_count = len(matching) - len(available)
            run.papers = available[:settings.count]
            run.status = "failed" if not successes else "partial" if failures else "success" if run.papers else "empty"
            run.note = {
                "failed": "所有查询均失败，本次不能判断是否有新论文；可手动重试。",
                "partial": "部分来源失败，已仅使用本次成功来源；可查看来源状态并手动重试。",
                "success": "已生成规则推荐；分数用于排序，不是论文质量或 AI 评价。",
                "empty": "本次成功查询的有限候选中没有未推荐论文，可调整主题或回溯天数。",
            }[run.status]
        except asyncio.CancelledError:
            if active and not active.done:
                await self.search.cancel(active)
            run.status, run.note = "interrupted", "服务停止，生成中断；可手动重新生成。"
            run.papers = []
        except Exception:
            run.status, run.note = "failed", "生成失败，未计入推荐去重；可手动重试。"
            run.papers = []
        run.finished_at = now()
        state = self.state.model_copy(deep=True)
        state.runs = [run if r.id == run.id else r for r in state.runs]
        try:
            self.commit(state)
        except OSError:
            # Never report success when the result wasn't saved.
            pass

    async def tick(self, current: datetime | None = None):
        current = (current or datetime.now(BEIJING)).astimezone(BEIJING)
        settings = self.state.settings
        if self.storage_error or not settings.enabled or (self.runner and not self.runner.done()):
            return
        if current.strftime("%H:%M") < settings.time or any(r.date == str(current.date()) for r in self.state.runs):
            return
        # Persisted reservation prevents repeated catch-up, including failed/interrupted runs.
        self.start("scheduled", current)

    async def loop(self):
        while True:
            try:
                await self.tick()
            except (SourceError, OSError):
                pass
            await asyncio.sleep(30)

    async def close(self):
        for task in (self.scheduler, self.runner):
            if task and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

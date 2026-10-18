from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .models import Record, SearchRequest, Source, SourceData, SourceStatus, now
from .sources import Providers, SourceError, effective_end_date


def identities(record: Record) -> set[str]:
    result = {f"{record.source}:{record.source_id}"}
    if record.source == "conferences" and record.index_provider in (None, "OpenAlex"):
        result.add(f"openalex:{record.source_id}")
    result.update(key for key in record.related_ids if re.fullmatch(r'openreview:[\w-]+', key))
    if record.source == 'conferences' and record.conference and record.publication_year and record.authors:
        normalize = lambda text: ' '.join(re.findall(r'\w+', text.casefold()))
        authors = '|'.join(sorted(normalize(a) for a in record.authors))
        result.add(f'conference-bib:{record.conference}:{record.publication_year}:{normalize(record.title)}:{authors}')
    if record.doi:
        result.add(f"doi:{record.doi}")
    if record.arxiv_id:
        result.add(f"arxiv:{record.arxiv_id}")
    return result


def merge_records(records: list[Record], sort: str) -> list[dict]:
    """Join by exact identifiers, including bridging records; never fuzzy-title merge."""
    groups: list[tuple[set[str], list[Record]]] = []
    for record in records:
        keys, members = identities(record), [record]
        remainder = []
        for group_keys, group_members in groups:
            if keys & group_keys:
                keys |= group_keys
                members += group_members
            else:
                remainder.append((group_keys, group_members))
        # The new identifiers may bridge a group examined earlier.
        changed = True
        while changed:
            changed = False
            for index, (group_keys, group_members) in enumerate(remainder):
                if keys & group_keys:
                    keys |= group_keys
                    members += group_members
                    remainder.pop(index)
                    changed = True
                    break
        groups = remainder + [(keys, members)]
    papers = []
    priority = {"arxiv": 0, "openreview": 1, "conferences": 2, "openalex": 3, "huggingface": 4}
    for keys, members in groups:
        members.sort(key=lambda r: (r.cached, priority[r.source], r.rank))
        primary = members[0]
        abstract_record = next((r for r in members if r.abstract), None)
        # The conference channel uses OpenAlex too: do not count it as independent evidence.
        families = {}
        for record in members:
            family = ("dblp" if record.index_provider == "DBLP" else "openalex") if record.source == "conferences" else record.source
            families[family] = min(families.get(family, record.rank), record.rank)
        score = sum(1 / (60 + rank) for rank in families.values())
        papers.append({
            "id": sorted(keys)[0], "title": primary.title,
            "authors": next((r.authors for r in members if r.authors), []),
            "abstract": abstract_record.abstract if abstract_record else None,
            "abstract_source": abstract_record.source if abstract_record else None,
            "year": primary.publication_year,
            "date": primary.filter_date, "date_kind": "仅年份" if primary.publication_year and not primary.filter_date else "首次提交" if primary.source == "arxiv" else "公开日期" if primary.source == "openreview" else "发表日期",
            "date_source": primary.source,
            "doi": next((r.doi for r in members if r.doi), None),
            "arxiv_id": next((r.arxiv_id for r in members if r.arxiv_id), None),
            "sources": list(dict.fromkeys(r.source for r in members)),
            "evidence": [r.model_dump() for r in members],
            "score": score,
        })
    if sort == "date":
        papers.sort(key=lambda p: (p["date"] or (f"{p['year']}-00-00" if p.get("year") else ""), p["score"], p["id"]), reverse=True)
    else:
        papers.sort(key=lambda p: (-p["score"], p["id"]))
    return papers


class Cache:
    def __init__(self, directory: Path):
        self.directory = directory

    def path(self, source: Source, request: SearchRequest) -> Path:
        payload = request.model_dump(mode="json", exclude={"sources"})
        payload["effective_end_date"] = str(effective_end_date(request))
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        # v2 scopes OpenAlex to title/abstract and enforces a current-date ceiling.
        # Never preview v1's broad/fulltext or future-dated results after upgrading.
        return self.directory / f"v2-{source}-{digest}.json"

    def read(self, source: Source, request: SearchRequest) -> SourceData | None:
        path = self.path(source, request)
        try:
            if time.time() - path.stat().st_mtime > 86400:
                return None
            return SourceData.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def write(self, source: Source, request: SearchRequest, data: SourceData) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path(source, request)
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(data.model_dump_json(), encoding="utf-8")
            os.replace(temporary, path)
            for old in sorted(self.directory.glob("v2-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[200:]:
                old.unlink(missing_ok=True)
        finally:
            temporary.unlink(missing_ok=True)


@dataclass
class SearchTask:
    request: SearchRequest
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_at: str = field(default_factory=now)
    statuses: dict[Source, SourceStatus] = field(default_factory=dict)
    records: dict[Source, list[Record]] = field(default_factory=dict)
    revision: int = 0
    done: bool = False
    runner: asyncio.Task | None = None
    changed: asyncio.Event = field(default_factory=asyncio.Event)

    def update(self):
        self.revision += 1
        self.changed.set()

    def snapshot(self) -> dict:
        raw = [record for values in self.records.values() for record in values]
        papers = merge_records(raw, self.request.sort)
        return {
            "id": self.id, "request": self.request.model_dump(mode="json"),
            "started_at": self.started_at, "done": self.done, "revision": self.revision,
            "sources": [self.statuses[s].model_dump() for s in self.request.sources],
            "papers": papers, "raw_count": len(raw), "merged_count": len(raw) - len(papers),
        }


class SearchService:
    def __init__(self, providers: Providers, cache: Cache):
        self.providers = providers
        self.cache = cache
        self.tasks: dict[str, SearchTask] = {}

    def create(self, request: SearchRequest) -> SearchTask:
        for identifier, task in list(self.tasks.items()):
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(task.started_at)).total_seconds()
            if task.done and (age > 1800 or len(self.tasks) >= 40):
                del self.tasks[identifier]
        if sum(not task.done for task in self.tasks.values()) >= 4:
            raise SourceError("busy", "已有 4 个检索任务正在进行，请等待或取消任务。")
        task = SearchTask(request=request)
        for source in request.sources:
            status = SourceStatus(source=source)
            cached = self.cache.read(source, request)
            if cached:
                task.records[source] = [r.model_copy(update={"cached": True}) for r in cached.records]
                status.cached_at = cached.retrieved_at
                status.count = len(cached.records)
                status.note = "正在显示上次缓存，并发起实时刷新。 " + cached.note
                status.total = cached.total
                status.scanned = cached.scanned
            task.statuses[source] = status
        self.tasks[task.id] = task
        task.runner = asyncio.create_task(self.run(task))
        return task

    async def run_source(self, task: SearchTask, source: Source):
        status = task.statuses[source]
        status.state = "running"
        task.update()
        try:
            async with asyncio.timeout(65):
                data = await self.providers.search(source, task.request)
            task.records[source] = data.records
            status.state = "limited" if data.limited else "success"
            status.count = len(data.records)
            status.scanned = data.scanned
            status.total = data.total
            status.note = data.note
            status.retrieved_at = data.retrieved_at
            status.cached_at = None
            try:
                self.cache.write(source, task.request, data)
            except OSError:
                status.note += " 本次结果可用，但本地缓存写入失败。"
        except asyncio.CancelledError:
            status.state = "cancelled"
            status.note = "检索已取消。" + (" 保留的结果来自上次缓存。" if status.cached_at else "")
            raise
        except Exception as exc:
            status.state = "error"
            if isinstance(exc, SourceError):
                status.error_code, status.note = exc.code, exc.message
            elif isinstance(exc, TimeoutError):
                status.error_code, status.note = "timeout", "来源等待超时，请稍后重试。"
            else:
                status.error_code, status.note = "invalid_response", "来源响应格式异常，未将其视为无结果。"
            if status.cached_at:
                status.note += " 页面保留上次缓存，不能代表本次实时结果。"
        finally:
            task.update()

    async def run(self, task: SearchTask):
        try:
            await asyncio.gather(*(self.run_source(task, source) for source in task.request.sources))
        finally:
            task.done = True
            task.update()

    async def cancel(self, task: SearchTask):
        if task.runner and not task.runner.done():
            task.runner.cancel()
            await asyncio.gather(task.runner, return_exceptions=True)
        for status in task.statuses.values():
            if status.state in ("pending", "running"):
                status.state = "cancelled"
                status.note = "检索已取消。"
        task.done = True
        task.update()

    async def close(self):
        await asyncio.gather(*(self.cancel(task) for task in self.tasks.values() if not task.done))

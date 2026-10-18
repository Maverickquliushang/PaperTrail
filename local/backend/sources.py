from __future__ import annotations

import asyncio
import re
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import unquote, urlparse

import httpx
from defusedxml import ElementTree

from .models import SOURCES, Record, SearchRequest, Source, SourceData, now
from .conferences import CONFERENCE_SOURCES, OPENREVIEW_GROUPS

ARXIV_PATTERN = r"(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?"


class SourceError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def clean(value: object) -> str:
    return " ".join(str(value or "").split())


def safe_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlparse(value)
        if parsed.scheme in ("https", "http") and parsed.hostname and not parsed.username:
            return value
    except ValueError:
        pass
    return None


def doi_id(value: object) -> str | None:
    value = unquote(clean(value)).lower()
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value)
    return value if re.fullmatch(r"10\.\d{4,9}/\S+", value) else None


def arxiv_id(value: object) -> str | None:
    value = unquote(clean(value))
    value = re.sub(r"^(?:https?://(?:www\.|export\.)?arxiv\.org/(?:abs|pdf)/|arxiv:|10\.48550/arxiv\.)", "", value, flags=re.I)
    value = re.sub(r"\.pdf$", "", value)
    if re.fullmatch(ARXIV_PATTERN, value, re.I):
        return re.sub(r"v\d+$", "", value, flags=re.I).lower()
    return None


def day(value: object) -> str | None:
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except (TypeError, ValueError):
        return None


def effective_end_date(request: SearchRequest) -> date:
    today = datetime.now(timezone(timedelta(hours=8))).date()
    return min(request.end_date or today, today)


def within_dates(record: Record, request: SearchRequest) -> bool:
    value = record.filter_date
    if not value:
        return not (request.start_date or request.end_date)
    return (not request.start_date or value >= str(request.start_date)) and (
        value <= str(effective_end_date(request))
    )


def parse_arxiv(content: bytes, retrieved: str) -> tuple[list[Record], int]:
    root = ElementTree.fromstring(content)
    ns = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom", "o": "http://a9.com/-/spec/opensearch/1.1/"}
    if root.tag != "{http://www.w3.org/2005/Atom}feed":
        raise ValueError("Expected arXiv Atom feed")
    total_text = root.findtext("o:totalResults", None, ns)
    if total_text is None:
        raise SourceError("invalid_response", "arXiv 返回异常或查询错误，未将其视为无结果。")
    total = int(total_text)
    records = []
    for rank, entry in enumerate(root.findall("a:entry", ns), 1):
        raw_id = entry.findtext("a:id", "", ns)
        if "/api/errors" in raw_id:
            raise SourceError("query_rejected", "arXiv 无法处理该查询，请缩短或调整关键词。")
        identifier = arxiv_id(raw_id)
        if not identifier:
            continue
        records.append(Record(
            source="arxiv", source_id=raw_id, arxiv_id=identifier,
            doi=doi_id(entry.findtext("x:doi", "", ns)),
            title=clean(entry.findtext("a:title", "未提供标题", ns)),
            authors=[clean(a.findtext("a:name", "", ns)) for a in entry.findall("a:author", ns)],
            abstract=clean(entry.findtext("a:summary", "", ns)) or None,
            url=safe_url(raw_id) or f"https://arxiv.org/abs/{identifier}",
            pdf_url=next((safe_url(link.get("href")) for link in entry.findall("a:link", ns) if link.get("title") == "pdf"), None),
            venue=clean(entry.findtext("x:journal_ref", "", ns)) or None,
            submitted_date=day(entry.findtext("a:published", "", ns)),
            updated_date=day(entry.findtext("a:updated", "", ns)),
            retrieved_at=retrieved, rank=rank,
        ))
    return records, total


def decode_abstract(index: object) -> str | None:
    if not isinstance(index, dict):
        return None
    words = {}
    for word, positions in index.items():
        if isinstance(positions, list):
            for position in positions:
                if isinstance(position, int) and 0 <= position < 30000:
                    words[position] = word
    return " ".join(words[p] for p in sorted(words)) or None


def parse_openalex(data: dict, retrieved: str) -> tuple[list[Record], int]:
    if not isinstance(data.get("results"), list):
        raise ValueError("Missing results")
    records = []
    for rank, item in enumerate(data["results"], 1):
        primary = item.get("primary_location") or {}
        best = item.get("best_oa_location") or {}
        locations = item.get("locations") or [primary]
        doi = doi_id(item.get("doi"))
        identifier = arxiv_id(doi)
        if not identifier:
            identifier = next((ident for loc in locations if (ident := arxiv_id(loc.get("landing_page_url")))), None)
        records.append(Record(
            source="openalex", source_id=item["id"], doi=doi, arxiv_id=identifier,
            title=clean(item.get("title") or item.get("display_name")) or "未提供标题",
            authors=[clean((a.get("author") or {}).get("display_name")) for a in item.get("authorships", []) if (a.get("author") or {}).get("display_name")],
            abstract=decode_abstract(item.get("abstract_inverted_index")),
            url=safe_url(primary.get("landing_page_url")) or safe_url(item.get("id")) or "https://openalex.org",
            pdf_url=safe_url(best.get("pdf_url")) or safe_url(primary.get("pdf_url")),
            venue=clean((primary.get("source") or {}).get("display_name")) or None,
            publication_date=day(item.get("publication_date")),
            # updated_date is OpenAlex metadata maintenance, not a paper revision date.
            retrieved_at=retrieved, rank=rank,
        ))
    return records, int((data.get("meta") or {}).get("count", len(records)))


def parse_huggingface(data: list, retrieved: str) -> list[Record]:
    if not isinstance(data, list):
        raise ValueError("Expected paper list")
    records = []
    for rank, item in enumerate(data, 1):
        paper = item.get("paper") or item
        identifier = arxiv_id(paper.get("id"))
        if not identifier:
            continue
        records.append(Record(
            source="huggingface", source_id=paper["id"], arxiv_id=identifier,
            title=clean(paper.get("title")) or "未提供标题",
            authors=[clean(a.get("name")) for a in paper.get("authors", []) if a.get("name")],
            # Keep the supplied abstract, never substitute the provider's AI summary.
            abstract=clean(paper.get("summary")) or None,
            url=f"https://huggingface.co/papers/{identifier}", pdf_url=f"https://arxiv.org/pdf/{identifier}",
            publication_date=day(paper.get("publishedAt")),
            listed_date=day(item.get("submittedOnDailyAt")),
            retrieved_at=retrieved, rank=rank,
        ))
    return records


def parse_openreview(data: dict, retrieved: str, conferences: list[str]) -> list[Record]:
    if not isinstance(data.get("notes"), list):
        raise ValueError("Missing OpenReview notes")
    records = []
    for rank, item in enumerate(data["notes"], 1):
        content = item.get("content") or {}
        def value(key):
            raw = content.get(key)
            return raw.get("value") if isinstance(raw, dict) else raw
        venue_id = clean(value("venueid"))
        match = re.fullmatch(r"(ICLR|ICML|NeurIPS)\.cc/(\d{4})/Conference", venue_id)
        # Reject workshops, submissions, withdrawn and rejected papers, and replies.
        if not match or match[1] not in conferences or item.get("replyto"):
            continue
        identifier = item.get("id")
        if not isinstance(identifier, str) or not re.fullmatch(r"[\w-]+", identifier):
            continue
        def epoch_day(raw):
            try:
                return datetime.fromtimestamp(float(raw) / 1000, timezone.utc).date().isoformat() if raw else None
            except (TypeError, ValueError, OverflowError, OSError):
                return None
        pdf = value("pdf")
        if isinstance(pdf, str) and pdf.startswith("/pdf?"):
            pdf = "https://openreview.net" + pdf
        records.append(Record(
            source="openreview", source_id=identifier, title=clean(value("title")) or "未提供标题",
            authors=[clean(a) for a in (value("authors") or [])], abstract=clean(value("abstract")) or None,
            url=f"https://openreview.net/forum?id={identifier}", pdf_url=safe_url(pdf),
            doi=doi_id(value("doi")), arxiv_id=arxiv_id(value("arxiv_id")) or arxiv_id(value("html")),
            venue=clean(value("venue")) or f"{match[1]} {match[2]}", conference=match[1],
            publication_date=epoch_day(item.get("pdate")), submitted_date=epoch_day(item.get("cdate")),
            retrieved_at=retrieved, rank=rank,
        ))
    return records


class Providers:
    def __init__(self, client: httpx.AsyncClient, openalex_key: str = ""):
        self.client = client
        self.openalex_key = openalex_key
        self.locks = {source: asyncio.Lock() for source in SOURCES}
        self.locks["conferences"] = self.locks["openalex"]
        self.last_request = {source: 0.0 for source in self.locks}

    async def request(self, source: Source, url: str, params: dict) -> bytes:
        if source == "conferences":
            source = "openalex"
        headers = {"Authorization": f"Bearer {self.openalex_key}"} if source == "openalex" and self.openalex_key else {}
        for attempt in range(2):
            async with self.locks[source]:
                interval = 3.1 if source == "arxiv" else 0.25
                await asyncio.sleep(max(0, interval - (time.monotonic() - self.last_request[source])))
                self.last_request[source] = time.monotonic()
                try:
                    async with self.client.stream("GET", url, params=params, headers=headers) as response:
                        if response.status_code in (429, 500, 502, 503, 504):
                            retry_after = response.headers.get("retry-after", "2")
                            delay = float(retry_after) if retry_after.isdigit() else 2.0
                            if attempt == 0 and delay <= 8:
                                await asyncio.sleep(max(delay, 1))
                                continue
                            code = "rate_limited" if response.status_code == 429 else "upstream_error"
                            raise SourceError(code, f"来源限流或暂时不可用（HTTP {response.status_code}），请稍后重试。")
                        if response.status_code in (401, 403):
                            message = "OpenAlex 拒绝访问；可在本地 .env 配置 OPENALEX_API_KEY 后重启。" if source == "openalex" else "来源拒绝访问，请检查网络或来源访问限制。"
                            raise SourceError("access_denied", message)
                        if response.status_code >= 400:
                            raise SourceError("http_error", f"来源返回 HTTP {response.status_code}，这不表示没有论文。")
                        chunks = bytearray()
                        async for chunk in response.aiter_bytes():
                            chunks.extend(chunk)
                            if len(chunks) > 8 * 1024 * 1024:
                                raise SourceError("response_too_large", "来源响应超过本次安全大小上限，请缩小检索范围。")
                        return bytes(chunks)
                except httpx.TimeoutException:
                    if attempt:
                        raise SourceError("timeout", "来源请求超时，请稍后重试。") from None
                except httpx.RequestError:
                    if attempt:
                        raise SourceError("network_error", "无法连接来源，请检查网络、系统代理或证书。") from None
            await asyncio.sleep(1)
        raise SourceError("network_error", "来源连接失败。")

    async def search(self, source: Source, request: SearchRequest) -> SourceData:
        import json

        end_date = effective_end_date(request)
        if request.start_date and request.start_date > end_date:
            return SourceData(records=[], total=0, scanned=0, retrieved_at=now(),
                              note="开始日期晚于今天；当前检索不展示未来发表日期的记录。")
        if source == "arxiv":
            # Treat the input as keywords, rather than exposing arXiv's query language.
            terms = re.findall(r"[\w-]+", request.query, re.UNICODE)
            query = " AND ".join(f'all:"{term}"' for term in terms)
            start = (request.start_date or date(1991, 1, 1)).strftime("%Y%m%d") + "0000"
            end = end_date.strftime("%Y%m%d") + "2359"
            query += f" AND submittedDate:[{start} TO {end}]"
            body = await self.request(source, "https://export.arxiv.org/api/query", {
                "search_query": query, "start": 0, "max_results": request.limit,
                "sortBy": "submittedDate" if request.sort == "date" else "relevance", "sortOrder": "descending",
            })
            retrieved = now()
            records, total = parse_arxiv(body, retrieved)
            note = "按 arXiv 首次提交日期筛选（UTC）；关键词以 AND 连接。"
            limited = total > request.limit
            scanned = len(records)
        elif source in ("openalex", "conferences"):
            # A fulltext-only mention must not outrank topical papers just because
            # its publication date is newer. Use OpenAlex's scoped text search.
            params: dict = {"search.title_and_abstract": request.query, "per_page": request.limit}
            filters = []
            if source == "conferences":
                ids = [identifier for conference in request.conferences for identifier in CONFERENCE_SOURCES[conference]]
                filters.append("primary_location.source.id:" + "|".join(ids))
            if request.start_date:
                filters.append(f"from_publication_date:{request.start_date}")
            filters.append(f"to_publication_date:{end_date}")
            if filters:
                params["filter"] = ",".join(filters)
            if request.sort == "date":
                params["sort"] = "publication_date:desc"
            body = await self.request(source, "https://api.openalex.org/works", params)
            retrieved = now()
            records, total = parse_openalex(json.loads(body), retrieved)
            note = "仅匹配 OpenAlex 标题和摘要，不使用全文中的零散提及；按索引发表日期筛选，可能不同于预印本提交日期。"
            if source == "conferences":
                lookup = {identifier: conference for conference in request.conferences for identifier in CONFERENCE_SOURCES[conference]}
                items = json.loads(body)["results"]
                for record, item in zip(records, items):
                    source_id = ((item.get("primary_location") or {}).get("source") or {}).get("id", "").rsplit("/", 1)[-1]
                    record.source = "conferences"
                    record.conference = lookup.get(source_id)
                records = [r for r in records if r.conference]
                note = "仅匹配标题和摘要；按已核对的 OpenAlex 会议论文集 ID 筛选，非会议官网全量抓取；ICML、ICLR、ECCV 索引覆盖尤其有限。日期为索引发表日期，录用状态以原文为准。"
            limited = total > request.limit
            scanned = len(records)
        elif source == "openreview":
            candidates = []
            scanned = 0
            for conference in request.conferences:
                if conference not in OPENREVIEW_GROUPS:
                    continue
                body = await self.request(source, "https://api2.openreview.net/notes/search", {
                    "term": request.query, "content": "all", "group": OPENREVIEW_GROUPS[conference],
                    "source": "forum", "limit": 100,
                })
                data = json.loads(body)
                parsed = parse_openreview(data, now(), request.conferences)
                scanned += len(data["notes"])
                candidates.extend(parsed)
            retrieved = now()
            records = list({r.source_id: r for r in candidates if within_dates(r, request)}.values())
            if request.sort == "date":
                records.sort(key=lambda r: r.publication_date or "", reverse=True)
            else:
                records.sort(key=lambda r: (r.rank, r.source_id))
            records = records[:request.limit]
            total, limited = None, True
            note = "直接检索 OpenReview：仅保留 ICLR / ICML / NeurIPS 主会已录用 venueid，排除拒稿、撤稿和 workshop。每会前 100 条候选内筛日期和排序，日期为 pdate（公开时间），不是会议举办日；历史 API v1 会议可能缺失。"
            if not any(c in OPENREVIEW_GROUPS for c in request.conferences):
                note = "所选会议不在此来源的 ICLR / ICML / NeurIPS 范围内，可查看顶会索引来源。"
        else:
            # The official search endpoint only exposes q and limit; no date filter/paging.
            body = await self.request(source, "https://huggingface.co/api/papers/search", {"q": request.query, "limit": 120})
            retrieved = now()
            candidates = parse_huggingface(json.loads(body), retrieved)
            scanned = len(candidates)
            records = [record for record in candidates if within_dates(record, request)]
            if request.sort == "date":
                records.sort(key=lambda r: r.publication_date or "", reverse=True)
            records = records[:request.limit]
            total = None
            limited = True
            note = "仅搜索 Hugging Face 收录论文；在相关性最高的至多 120 条候选内按论文 publishedAt 筛日期/排序，不保证日期范围内全量覆盖，总命中数未知。"
        if limited and source not in ("huggingface", "openreview"):
            note += f" 本次仅取前 {request.limit} 条，未拉取后续页。"
        # Defend against out-of-range metadata even when an upstream ignored its filter.
        filtered = [record for record in records if within_dates(record, request)]
        if len(filtered) != len(records):
            note += f" 已排除 {len(records) - len(filtered)} 条日期不符合范围的记录。"
        records = filtered
        note += f" 本次日期截止 {end_date}，未来发表日期不作为已发表结果展示。"
        return SourceData(records=records, total=total, scanned=scanned, limited=limited, note=note, retrieved_at=retrieved)

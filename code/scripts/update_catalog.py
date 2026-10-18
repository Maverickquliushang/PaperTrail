"""Batch collection only: no app server, personal config, Feishu or model calls."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "local"))
import httpx
from backend.models import Record, SOURCES
from backend.conferences import CONFERENCE_SOURCES

from backend.sources import SourceError
# Support both direct execution and unittest imports.
sys.path.insert(0, str(ROOT))
from scripts.latest_sources import LatestProviders
from scripts.public_records import PublicRecord, DBLP_STREAMS
from scripts.catalog_storage import merge_records, read_catalog, write_catalog
from scripts.conference_sync import needs_backfill

BEIJING = timezone(timedelta(hours=8))


def validate_config(value):
    if value.get("mode") != "ai_latest" or "topics" in value:
        raise ValueError("Public collection uses AI categories, without personal topics")
    if not value.get("sources") or len(set(value["sources"])) != len(value["sources"]) or not set(value["sources"]) <= set(SOURCES):
        raise ValueError("Unknown or duplicate source")
    for key, low, high in [("community_feed_days", 1, 30), ("candidate_limit", 1, 100), ("history_days", 1, 90)]:
        if type(value.get(key)) is not int or not low <= value[key] <= high:
            raise ValueError(f"Invalid {key}")
    return value


load_catalog = read_catalog

def eligible(record, today):
    if record.filter_date:
        return record.filter_date <= str(today)
    year = getattr(record, 'publication_year', None)
    return year is None or year <= today.year


async def collect(config, previous, providers, instant=None, backfill_only=False):
    # Do not migrate personalized catalogs or their histories into the public feed.
    if previous.get("schema") != 2 or previous.get("mode") != "ai_latest":
        previous = {}
    instant = instant or datetime.now(BEIJING)
    today = instant.astimezone(BEIJING).date()
    stamp = instant.isoformat()
    start = today - timedelta(days=config["community_feed_days"] - 1)
    fresh, statuses = [], {}
    providers.conference_state = previous.get("conference_sync", {})
    providers.source_state = previous.get("source_sync", {})
    providers.official_state = previous.get("official_sync", {})
    for source in config["sources"]:
        records, reports = [], []
        try:
            data = await providers.latest(source, start, today, config["candidate_limit"])
            records.extend(r for r in data.records if eligible(r, today))
            reports.extend(getattr(data, "reports", []) or [{"label": "AI 最新论文", "state": "partial" if getattr(data, "partial", False) else "limited" if data.limited else "success",
                            "count": len(records), "note": data.note}])
        except Exception as exc:
            if source in ('arxiv','openalex'):
                entry=providers.source_state.setdefault(source,{'end':str(today),'boundary':str(today),'offset':0,'scanned':0,'pages':0,'complete':False,'pending':True})
                entry['error']=exc.message if isinstance(exc,SourceError) else '来源请求未完成。'
                if isinstance(exc,SourceError) and exc.code in ('access_denied','rate_limited'):
                    entry['retry_after']=str(today+timedelta(days=1))
            reports.append({"label": "AI 最新论文", "state": "error", "count": 0,
                            "note": exc.message if isinstance(exc, SourceError) else "来源请求未完成，请稍后重试。"})
        old_reports = {r.get("label"): r for r in previous.get("source_status", {}).get(source, {}).get("queries", [])}
        for report in reports:
            report["updated_at"] = stamp if report["state"] != "error" and not report.get('cached') else old_reports.get(report.get("label"), {}).get("updated_at")
        successes = sum(r["state"] != "error" for r in reports)
        state = "error" if not successes else "partial" if successes < len(reports) or any(r["state"] in ("partial", "limited") for r in reports) else "success"
        statuses[source] = {"state": state, "attempted_at": stamp,
                            "updated_at": stamp if successes else previous.get("source_status", {}).get(source, {}).get("updated_at"),
                            "queries": reports, "fresh_count": len({r.source_id for r in records})}
        fresh.extend(records)

    # Retain historical public metadata without a rolling date cutoff; never recommend stale
    # records as fresh after an upstream failure. Exact IDs, not fuzzy titles, dedupe.
    retained = {}
    for paper in previous.get("papers", []):
        for evidence in paper.get("evidence", []):
            r = PublicRecord.model_validate(evidence)
            if r.source == "openreview" and not r.review_status:
                r.review_status = "accepted"  # Earlier catalogs only collected accepted papers.
            if r.source == "conferences" and r.index_provider in (None, 'OpenAlex'):
                continue  # Legacy conference OpenAlex records; separate OpenAlex source is retained.
            if r.source in config["sources"] and eligible(r, today):
                retained[(r.source, r.source_id)] = r
    for r in fresh:
        retained[(r.source, r.source_id)] = r
    papers = merge_records(list(retained.values()), "date")
    def annotate(items):
        for p in items:
            if p.get("date_source") == "openreview":
                p["date_kind"] = "录用日期" if (p["evidence"][0].get("review_status") or "accepted") == "accepted" else "投稿创建日期"
            if not p.get("date"):
                p["year"] = next((e.get("publication_year") for e in p["evidence"] if e.get("publication_year")), None)
                p["date_kind"] = "仅年份" if p["year"] else "日期未知"
        return items
    annotate(papers)
    cutoff = str(today - timedelta(days=config["history_days"] - 1))
    history = [h for h in previous.get("history", []) if cutoff <= h["date"] <= str(today)]
    recommendations = {}
    old_today = next((h for h in history if h["date"] == str(today)), {})
    for source in config["sources"]:
        seen = {p["id"] for h in history if h["date"] != str(today)
                for p in h.get("recommendations", {}).get(source, {}).get("papers", [])}
        # A same-day retry may retain successfully generated papers, explicitly dated.
        saved = old_today.get("recommendations", {}).get(source, {}).get("papers", [])
        choices = {p["id"]: p for p in saved if p.get("date") == str(today)}
        candidates = annotate(merge_records(list({r.source_id: r for r in retained.values() if r.source == source}.values()), "date"))
        for p in candidates:
            if source in p["sources"] and p["id"] not in seen and p.get("date") == str(today) and (source != "openreview" or any(e["source"] == "openreview" and (e.get("review_status") or "accepted") == "accepted" for e in p["evidence"])):
                choices[p["id"]] = p
        selected = sorted(choices.values(), key=lambda p: (p["date"] or "", p["id"]), reverse=True)
        recommendations[source] = {"date": str(today), "state": statuses[source]["state"], "papers": selected}
    public_reports = [r for r in statuses.get("openreview", {}).get("queries", []) if r.get("view") == "public"]
    public_state = ("error" if not public_reports or all(r["state"] == "error" for r in public_reports)
                    else "partial" if any(r["state"] == "error" for r in public_reports) else "success")
    public_choices = {p["id"]: p for p in old_today.get("openreview_public", {}).get("papers", []) if p.get("date") == str(today)}
    public_seen = {p["id"] for h in history if h["date"] != str(today) for p in h.get("openreview_public", {}).get("papers", [])}
    for p in annotate(merge_records(list({r.source_id:r for r in retained.values() if r.source == "openreview"}.values()), "date")):
        if p.get("date") == str(today) and p["id"] not in public_seen:
            public_choices[p["id"]] = p
    public_daily = {"state": public_state, "papers": sorted(public_choices.values(), key=lambda p:(p["date"],p["id"]), reverse=True)}
    history = [h for h in history if h["date"] != str(today)]
    history.append({"date": str(today), "recommendations": recommendations, "openreview_public": public_daily})
    if backfill_only:
        history = previous.get('history', [])
        recommendations = previous.get('recommendations', {})
    conference_counts = {name: sum(any(e['source'] == 'conferences' and e.get('conference') == name for e in p['evidence']) for p in papers) for name in CONFERENCE_SOURCES}
    any_success = any(s["state"] != "error" for s in statuses.values())
    return {"schema": 2, "mode": "ai_latest", "attempted_at": stamp,
            "updated_at": stamp if any_success else previous.get("updated_at"),
            "search_start_date": None, "community_feed_days": config["community_feed_days"],
            "conference_catalog": {"names": list(CONFERENCE_SOURCES), "dblp_streams": DBLP_STREAMS, "start_date": None, "counts": conference_counts, "total": sum("conferences" in p["sources"] for p in papers)},
            "conference_sync": getattr(providers, "conference_state", {}),
            "source_sync": getattr(providers, "source_state", {}),
            "official_sync": getattr(providers, "official_state", {}),
            "papers": papers, "source_status": statuses,
            "recommendations": recommendations, "history": history,
            "notice": "公共 AI 论文库，检索不设统一起始日期；会议论文分页累计收录，无总篇数上限；非全站实时搜索。每日推荐按来源日期浏览累计论文库，支持全部日期与各日篇数；仅年份记录不参与每日列表。"}


async def main():
    config = validate_config(json.loads((ROOT / "config/catalog.json").read_text(encoding="utf-8")))
    path = ROOT / "web/data/catalog.json"
    previous = load_catalog(path)
    backfill_only = os.getenv("PAPERTRAIL_BACKFILL_ONLY") == "true"
    if backfill_only and not needs_backfill({**previous.get("conference_sync", {}), **previous.get("source_sync", {})}, datetime.now(BEIJING).date()):
        print("No resumable conference backlog; waiting for daily refresh.")
        return
    async with httpx.AsyncClient(timeout=35, follow_redirects=True, headers={"User-Agent": "PaperTrail-Pages/1.0"}) as client:
        result = await collect(config, previous, LatestProviders(client, os.getenv("OPENALEX_API_KEY", "")), backfill_only=backfill_only)
    write_catalog(path, result)
    for source, status in result["source_status"].items():
        print(f"{source}: {status['state']}; fresh={status['fresh_count']}")
    if all(s["state"] == "error" for s in result["source_status"].values()):
        print("::warning::All sources failed; retained the previous catalog with explicit failure status.")


if __name__ == "__main__":
    asyncio.run(main())

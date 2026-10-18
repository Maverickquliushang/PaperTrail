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
from backend.search import merge_records
from backend.sources import SourceError
# Support both direct execution and unittest imports.
sys.path.insert(0, str(ROOT))
from scripts.latest_sources import LatestProviders

BEIJING = timezone(timedelta(hours=8))


def validate_config(value):
    if value.get("mode") != "ai_latest" or "topics" in value:
        raise ValueError("Public collection uses AI categories, without personal topics")
    if not value.get("sources") or len(set(value["sources"])) != len(value["sources"]) or not set(value["sources"]) <= set(SOURCES):
        raise ValueError("Unknown or duplicate source")
    for key, low, high in [("lookback_days", 1, 30), ("candidate_limit", 1, 100), ("recommendation_limit", 1, 10), ("history_days", 1, 90)]:
        if type(value.get(key)) is not int or not low <= value[key] <= high:
            raise ValueError(f"Invalid {key}")
    return value


def load_catalog(path):
    if not path.exists():
        return {"papers": [], "history": []}
    return json.loads(path.read_text(encoding="utf-8"))


async def collect(config, previous, providers, instant=None):
    # Do not migrate personalized catalogs or their histories into the public feed.
    if previous.get("schema") != 2 or previous.get("mode") != "ai_latest":
        previous = {}
    instant = instant or datetime.now(BEIJING)
    today = instant.astimezone(BEIJING).date()
    stamp = instant.isoformat()
    start = today - timedelta(days=config["lookback_days"] - 1)
    fresh, statuses = [], {}
    for source in config["sources"]:
        records, reports = [], []
        try:
            data = await providers.latest(source, start, today, config["candidate_limit"])
            records.extend(r for r in data.records if r.filter_date and str(start) <= r.filter_date <= str(today))
            reports.append({"label": "AI 最新论文", "state": "partial" if getattr(data, "partial", False) else "limited" if data.limited else "success",
                            "count": len(records), "note": data.note})
        except Exception as exc:
            reports.append({"label": "AI 最新论文", "state": "error", "count": 0,
                            "note": exc.message if isinstance(exc, SourceError) else "来源请求未完成，请稍后重试。"})
        successes = sum(r["state"] != "error" for r in reports)
        state = "error" if not successes else "partial" if successes < len(reports) or any(r["state"] == "partial" for r in reports) else "success"
        statuses[source] = {"state": state, "attempted_at": stamp,
                            "updated_at": stamp if successes else previous.get("source_status", {}).get(source, {}).get("updated_at"),
                            "queries": reports, "fresh_count": len({r.source_id for r in records})}
        fresh.extend(records)

    # Retain public metadata within the configured window, but never recommend stale
    # records as fresh after an upstream failure. Exact IDs, not fuzzy titles, dedupe.
    retained = {}
    for paper in previous.get("papers", []):
        for evidence in paper.get("evidence", []):
            r = Record.model_validate(evidence)
            if r.source in config["sources"] and r.filter_date and str(start) <= r.filter_date <= str(today):
                retained[(r.source, r.source_id)] = r
    for r in fresh:
        retained[(r.source, r.source_id)] = r
    papers = merge_records(list(retained.values()), "date")
    fresh_papers = merge_records(list({(r.source, r.source_id): r for r in fresh}.values()), "date")
    for p in papers + fresh_papers:
        if p.get("date_source") == "openreview":
            p["date_kind"] = "录用日期"
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
        for p in fresh_papers:
            if source in p["sources"] and p["id"] not in seen and p.get("date") == str(today):
                choices[p["id"]] = p
        selected = sorted(choices.values(), key=lambda p: (p["date"] or "", p["id"]), reverse=True)[:config["recommendation_limit"]]
        recommendations[source] = {"date": str(today), "state": statuses[source]["state"], "papers": selected}
    history = [h for h in history if h["date"] != str(today)]
    history.append({"date": str(today), "recommendations": recommendations})
    any_success = any(s["state"] != "error" for s in statuses.values())
    return {"schema": 2, "mode": "ai_latest", "attempted_at": stamp,
            "updated_at": stamp if any_success else previous.get("updated_at"),
            "lookback_days": config["lookback_days"],
            "papers": papers, "source_status": statuses,
            "recommendations": recommendations, "history": history,
            "notice": "公共 AI 分类论文库，非全站实时搜索。每日推荐仅选来源标注日期为当天的论文，每来源最多 10 篇；无结果不以旧论文补足。"}


async def main():
    config = validate_config(json.loads((ROOT / "config/catalog.json").read_text(encoding="utf-8")))
    path = ROOT / "web/data/catalog.json"
    previous = load_catalog(path)
    async with httpx.AsyncClient(timeout=35, follow_redirects=True, headers={"User-Agent": "PaperTrail-Pages/1.0"}) as client:
        result = await collect(config, previous, LatestProviders(client, os.getenv("OPENALEX_API_KEY", "")))
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)
    for source, status in result["source_status"].items():
        print(f"{source}: {status['state']}; fresh={status['fresh_count']}")
    if all(s["state"] == "error" for s in result["source_status"].values()):
        print("::warning::All sources failed; retained the previous catalog with explicit failure status.")


if __name__ == "__main__":
    asyncio.run(main())

"""Local cumulative library; shares collection and UI with the published edition."""
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY))
from scripts.update_catalog import collect, load_catalog, BEIJING, validate_config
from scripts.latest_sources import LatestProviders
from scripts.catalog_storage import write_catalog
from scripts.conference_sync import needs_backfill


class LibraryService:
    def __init__(self, root, client):
        self.path = root / 'data/library/catalog.json'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.client, self.runner, self.error = client, None, None
        self.next_attempt = 0
        if not self.path.exists():
            self.path.write_text(json.dumps({'schema':2,'mode':'ai_latest','papers':[],
                'source_status':{},'history':[],'conference_sync':{}}), encoding='utf-8')

    def overview(self):
        return {'running': bool(self.runner and not self.runner.done()), 'error': self.error,
                'url': '/library/', 'schedule': '每天北京时间 09:00；运行期间每小时续接历史补采'}

    def start(self, backfill_only=False):
        if not self.overview()['running']:
            self.runner = asyncio.create_task(self.update(backfill_only))
        return self.overview()

    async def update(self, backfill_only):
        self.error = None
        try:
            config = validate_config(json.loads((REPOSITORY / 'config/catalog.json').read_text(encoding='utf-8')))
            previous = await asyncio.to_thread(load_catalog, self.path)
            provider = LatestProviders(self.client, os.getenv('OPENALEX_API_KEY', ''))
            result = await collect(config, previous, provider, backfill_only=backfill_only)
            await asyncio.to_thread(write_catalog, self.path, result)
        except Exception:
            self.error = '本地论文库更新未完成，旧数据和已保存断点保留；请重试。'
        finally:
            self.next_attempt = time.monotonic() + 3600

    async def tick(self):
        if self.overview()['running'] or time.monotonic() < self.next_attempt:
            return
        value = json.loads(self.path.read_text(encoding='utf-8'))
        today = datetime.now(BEIJING)
        daily_due = today.hour >= 9 and not any(h['date'] == str(today.date()) for h in value.get('history', []))
        if not value.get('updated_at') or daily_due:
            self.start()
        elif needs_backfill(value.get('conference_sync', {}), today.date()):
            self.start(backfill_only=True)

    async def close(self):
        if self.runner and not self.runner.done():
            self.runner.cancel()
            await asyncio.gather(self.runner, return_exceptions=True)

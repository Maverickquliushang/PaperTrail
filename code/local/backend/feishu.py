"""Local Feishu application bot: explicit pairing, durable events and delivery ledger."""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field

from .models import SOURCES, Source, now
from .feishu_workspace import GroupWorkspace, NAMES, by_date
from .query_language import search_body
from .recommendations import BEIJING

class BotSettings(BaseModel):
    enabled: bool = False
    app_id: str = Field(default="", max_length=100)
    app_secret: str = Field(default="", max_length=300, repr=False)
    chat_id: str = ""
    owner_id: str = ""
    push_enabled: bool = False
    push_since: str | None = None
    push_sources: list[Source] = Field(default_factory=lambda: list(SOURCES))


class Credentials(BaseModel):
    app_id: str = Field(pattern=r"^cli_[A-Za-z0-9]+$", max_length=100)
    app_secret: str = Field(default="", max_length=300)
    enabled: bool = True


class PushSettings(BaseModel):
    enabled: bool
    sources: list[Source] = Field(min_length=1, max_length=5)


class Ledger(BaseModel):
    deliveries: dict[str, dict] = Field(default_factory=dict)
    events: dict[str, float] = Field(default_factory=dict)


def atomic_json(path: Path, value: BaseModel):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as out:
            out.write(value.model_dump_json())
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def paper_text(title: str, papers: list[dict], note: str = "") -> str:
    rows = [f"PaperTrail · {title}", "按日期从新到旧排列（未提供日期的论文放在最后）。", note[:800]]
    for index, paper in enumerate(by_date(papers)[:10], 1):
        url = next((e.get("url", "") for e in paper.get("evidence", []) if e.get("url", "").startswith(("https://", "http://"))), "")
        rows.append(f"{index}. {paper.get('title', '')[:240]}\n{paper.get('date') or '日期未提供'}\n{url[:600]}")
    if not papers:
        rows.append("本次没有可显示论文；请结合上方来源状态查看。")
    return "\n\n".join(filter(None, rows))


class FeishuService:
    def __init__(self, client: httpx.AsyncClient, search, recommendations, config_path: Path, state_path: Path):
        self.client, self.search, self.recommendations = client, search, recommendations
        self.config_path, self.state_path = config_path, state_path
        self.settings, self.ledger = BotSettings(), Ledger()
        self.error = ""
        self.connection = "未配置"
        self.bot_id = ""
        self.token, self.token_until = "", 0.0
        self.pair_code, self.pair_until = "", 0.0
        self.process = None
        self.listener = None
        self.registration = None
        self.registration_process = None
        self.authorization_url = ""
        self.registration_status = "尚未开始"
        self.jobs: set[asyncio.Task] = set()
        self.long_jobs: set[asyncio.Task] = set()
        self.workspace = GroupWorkspace(self)
        self.lock = asyncio.Lock()
        self.stopping = False
        self.storage_error = False
        try:
            if config_path.exists():
                self.settings = BotSettings.model_validate_json(config_path.read_text(encoding="utf-8"))
            if state_path.exists():
                self.ledger = Ledger.model_validate_json(state_path.read_text(encoding="utf-8"))
            # A crash after sending but before acknowledgement is deliberately not retried.
            if any(d["status"] == "sending" for d in self.ledger.deliveries.values()):
                for entry in self.ledger.deliveries.values():
                    if entry["status"] == "sending":
                        entry["status"] = "unknown"
                atomic_json(self.state_path, self.ledger)
        except (OSError, ValueError, KeyError):
            self.storage_error = True
            self.error = "飞书配置或投递记录读取失败，已停止接入并保留文件。"

    def guard(self):
        if self.storage_error:
            raise ValueError(self.error)

    def overview(self):
        return {"configured": bool(self.settings.app_id and self.settings.app_secret),
                "app_id": self.settings.app_id, "enabled": self.settings.enabled,
                "connection": self.connection, "error": self.error,
                "paired": bool(self.settings.chat_id and self.settings.owner_id),
                "chat_id": self.settings.chat_id, "push_enabled": self.settings.push_enabled,
                "push_sources": self.settings.push_sources,
                "authorization_url": self.authorization_url, "registration_status": self.registration_status,
                "deliveries": list(self.ledger.deliveries.values())[-20:][::-1]}

    def begin_registration(self):
        self.guard()
        if self.settings.app_id:
            raise ValueError("已有应用配置，请使用当前应用；需要更换时可手动填写新应用凭据。")
        if self.registration and not self.registration.done():
            return self.overview()
        self.authorization_url = ""
        self.registration_status = "正在准备飞书授权页面"
        self.registration = asyncio.create_task(self.register())
        return self.overview()

    async def register(self):
        try:
            options = {"creationflags": 0x08000000} if os.name == "nt" else {}
            self.registration_process = await asyncio.create_subprocess_exec(sys.executable, "-m", "backend.feishu_worker", "--register",
                cwd=Path(__file__).resolve().parents[1], stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, **options)
            async with asyncio.timeout(900):
                while line := await self.registration_process.stdout.readline():
                    payload = json.loads(line)
                    if payload.get("registration_error"):
                        kind = payload["registration_error"]
                        reasons = {"AppAccessDeniedError": "飞书授权被取消或拒绝", "AppExpiredError": "飞书授权链接已过期",
                                   "ConnectionError": "接收飞书授权结果时网络中断", "ReadTimeout": "接收飞书授权结果超时"}
                        self.registration_status = reasons.get(kind, "飞书没有返回可用授权结果") + "；可重新授权并选择已创建的应用，或手动填写凭据。"
                        return
                    url = payload.get("authorization_url")
                    if url:
                        parsed = urlsplit(url)
                        if parsed.scheme != "https" or not (parsed.hostname or "").endswith(".feishu.cn"):
                            raise ValueError("Unexpected authorization domain")
                        self.authorization_url = url
                        self.registration_status = "等待你在飞书页面确认授权"
                    if payload.get("credentials"):
                        if self.settings.app_id:
                            raise ValueError("Application configuration changed")
                        await self.save_credentials(Credentials(**payload["credentials"]))
                        self.registration_status = "应用凭据已自动保存，请把机器人加入目标群"
                        self.authorization_url = ""
                        return
            self.registration_status = "授权未完成，可重新开始或手动创建应用"
        except asyncio.CancelledError:
            raise
        except Exception:
            self.registration_status = "授权未完成，可重新开始或手动创建应用"
        finally:
            self.authorization_url = ""
            if self.registration_process and self.registration_process.returncode is None:
                self.registration_process.terminate()
                await self.registration_process.wait()
            self.registration_process = None

    async def save_credentials(self, value: Credentials):
        self.guard()
        secret = value.app_secret.strip() or (self.settings.app_secret if value.app_id == self.settings.app_id else "")
        if not secret:
            raise ValueError("请填写 App Secret。")
        await self.stop_listener()
        settings = self.settings.model_copy(deep=True)
        if settings.app_id != value.app_id:
            settings = BotSettings()
        settings.app_id, settings.app_secret, settings.enabled = value.app_id, secret, value.enabled
        atomic_json(self.config_path, settings)
        self.settings = settings
        self.token, self.token_until, self.bot_id = "", 0, ""
        self.error = ""
        self.start_listener()
        return self.overview()

    def start_pairing(self):
        self.guard()
        if not self.settings.enabled or not self.settings.app_secret:
            raise ValueError("请先保存应用凭据并启用连接。")
        if self.settings.chat_id:
            raise ValueError("已有绑定群，请先解绑。")
        self.pair_code = secrets.token_hex(5).upper()
        self.pair_until = time.time() + 600
        return {"code": self.pair_code, "expires_in": 600}

    def save_push(self, value: PushSettings):
        self.guard()
        if value.enabled and not (self.settings.enabled and self.settings.chat_id and self.settings.owner_id):
            raise ValueError("请先启用连接并绑定群聊。")
        settings = self.settings.model_copy(deep=True)
        if value.enabled and not settings.push_enabled:
            settings.push_since = now()
        settings.push_enabled = value.enabled
        settings.push_sources = list(dict.fromkeys(value.sources))
        atomic_json(self.config_path, settings)
        self.settings = settings
        return self.overview()

    async def unpair(self):
        self.guard()
        await self.stop_listener()
        settings = self.settings.model_copy(update={"chat_id": "", "owner_id": "", "push_enabled": False, "push_since": None})
        atomic_json(self.config_path, settings)
        self.settings = settings
        self.pair_code = ""
        self.start_listener()
        return self.overview()

    async def access_token(self):
        if self.token and time.time() < self.token_until:
            return self.token
        response = await self.client.post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                                          json={"app_id": self.settings.app_id, "app_secret": self.settings.app_secret}, timeout=15)
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0 or not data.get("tenant_access_token"):
            raise ValueError(f"飞书应用认证失败（代码 {data.get('code', '未知')}），请检查凭据和应用状态。")
        self.token = data["tenant_access_token"]
        self.token_until = time.time() + max(1, data.get("expire", 7200) - 120)
        return self.token

    async def identify_bot(self):
        token = await self.access_token()
        response = await self.client.get("https://open.feishu.cn/open-apis/bot/v3/info", headers={"Authorization": f"Bearer {token}"}, timeout=15)
        response.raise_for_status()
        data = response.json()
        self.bot_id = data.get("bot", {}).get("open_id", "")
        if data.get("code") != 0 or not self.bot_id:
            raise ValueError("无法确认机器人身份，请开启应用机器人能力并发布可用版本。")

    async def send(self, key: str, text: str):
        self.guard()
        async with self.lock:
            if not self.settings.enabled or not self.settings.chat_id:
                return
            target = self.settings.chat_id
            app_id = self.settings.app_id
            key = f"{self.settings.app_id}:{target}:{key}"
            if key in self.ledger.deliveries:
                return
            entry = {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, key)), "status": "preparing", "at": now(), "title": text.splitlines()[0][:120]}
            # Authentication happens before the send intent, so failures here are definite.
            try:
                token = await self.access_token()
            except (httpx.HTTPError, ValueError):
                entry["status"] = "failed"
                self.ledger.deliveries[key] = entry
                atomic_json(self.state_path, self.ledger)
                self.error = "飞书认证失败，本次未发送；请检查应用配置。"
                return
            if not self.settings.enabled or self.settings.chat_id != target or self.settings.app_id != app_id:
                return
            entry["status"] = "sending"
            self.ledger.deliveries[key] = entry
            atomic_json(self.state_path, self.ledger)
            try:
                response = await self.client.post("https://open.feishu.cn/open-apis/im/v1/messages", params={"receive_id_type": "chat_id"},
                    headers={"Authorization": f"Bearer {token}"}, json={"receive_id": target, "msg_type": "text",
                    "content": json.dumps({"text": text}, ensure_ascii=False), "uuid": entry["id"]}, timeout=20)
                data = response.json()
                if response.is_success and data.get("code") == 0 and data.get("data", {}).get("message_id"):
                    entry.update(status="sent", message_id=data["data"]["message_id"])
                else:
                    entry.update(status="unknown" if response.status_code >= 500 else "failed", code=data.get("code"))
            except (httpx.HTTPError, ValueError):
                entry["status"] = "unknown"
            finally:
                if entry["status"] == "sending":
                    entry["status"] = "unknown"
                atomic_json(self.state_path, self.ledger)

    async def handle_event(self, payload: dict):
        self.guard()
        if not self.settings.enabled:
            return
        event = payload.get("event", {})
        message, sender = event.get("message", {}), event.get("sender", {})
        identifier = message.get("message_id", "")
        owner = sender.get("sender_id", {}).get("open_id", "")
        chat = message.get("chat_id", "")
        try:
            age = time.time() - int(message.get("create_time", "0")) / 1000
            text = json.loads(message.get("content", "{}")).get("text", "")
        except (TypeError, ValueError):
            return
        if (not identifier or not owner or not chat or sender.get("sender_type") != "user" or message.get("chat_type") != "group"
                or message.get("message_type") != "text" or not isinstance(text, str) or len(text) > 8000 or not -60 <= age <= 600):
            return
        mentions = message.get("mentions", [])
        if not self.bot_id or not any(m.get("id", {}).get("open_id") == self.bot_id for m in mentions):
            return
        for mention in mentions:
            if mention.get("id", {}).get("open_id") == self.bot_id:
                text = text.replace(mention.get("key", "@_user_0"), "")
        text = text.strip()
        if (not self.settings.chat_id and self.pair_code and time.time() < self.pair_until
                and secrets.compare_digest(text.encode(), f"绑定 {self.pair_code}".encode())):
            settings = self.settings.model_copy(update={"chat_id": chat, "owner_id": owner})
            atomic_json(self.config_path, settings)
            self.settings, self.pair_code = settings, ""
            return  # The local page confirms pairing; this step sends no group message.
        if chat != self.settings.chat_id or owner != self.settings.owner_id:
            return
        event_key = f"{self.settings.app_id}:{identifier}"
        if event_key in self.ledger.events:
            return
        self.ledger.events = {k: t for k, t in self.ledger.events.items() if time.time() - t < 86400}
        self.ledger.events[event_key] = time.time()
        atomic_json(self.state_path, self.ledger)
        long_operation = search_body(text) is not None or (text.split(maxsplit=1)[0] == "生成推荐" if text else False)
        if long_operation and len(self.long_jobs) >= 2:
            await self.send(f"busy:{identifier}", "PaperTrail · 当前检索任务较多，请稍后再试。")
            return
        job = asyncio.create_task(self.command(identifier, text))
        self.jobs.add(job)
        job.add_done_callback(self.jobs.discard)
        if long_operation:
            self.long_jobs.add(job)
            job.add_done_callback(self.long_jobs.discard)

    async def command(self, identifier: str, text: str):
        await self.workspace.command(identifier, text)

    async def push_ready(self):
        self.guard()
        if not (self.settings.enabled and self.settings.push_enabled and self.settings.chat_id and self.settings.push_since):
            return
        today = str(datetime.now(BEIJING).date())
        for source in self.settings.push_sources:
            runs = self.recommendations()[source].state.runs
            run = next((r for r in reversed(runs) if r.date == today and r.trigger == "scheduled" and r.status not in ("running", "interrupted")
                        and datetime.fromisoformat(r.started_at) >= datetime.fromisoformat(self.settings.push_since)), None)
            if run:
                await self.send(f"daily:{source}:{today}", paper_text(f"{NAMES[source]} 每日推荐 · {today}", run.papers, run.note))

    def start_listener(self):
        if self.settings.enabled and self.settings.app_secret and not self.storage_error:
            self.stopping = False
            self.listener = asyncio.create_task(self.listen())
        else:
            self.connection = "未启用" if self.settings.app_id else "未配置"

    async def listen(self):
        while not self.stopping:
            try:
                self.connection = "连接中"
                await self.identify_bot()
                options = {"creationflags": 0x08000000} if os.name == "nt" else {}
                self.process = await asyncio.create_subprocess_exec(sys.executable, "-m", "backend.feishu_worker",
                    cwd=Path(__file__).resolve().parents[1], stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, **options)
                self.process.stdin.write((json.dumps({"app_id": self.settings.app_id, "app_secret": self.settings.app_secret}) + "\n").encode())
                await self.process.stdin.drain()
                while line := await self.process.stdout.readline():
                    try:
                        payload = json.loads(line)
                        if payload.get("status"):
                            self.connection = payload["status"]
                            if self.connection == "已连接":
                                self.error = ""
                        elif "event" in payload:
                            await self.handle_event(payload)
                    except (ValueError, TypeError):
                        continue
                await self.process.wait()
                self.connection = "连接中断，30 秒后重试"
            except asyncio.CancelledError:
                raise
            except Exception:
                self.connection = "连接失败，30 秒后重试"
                self.error = "请检查 App ID、App Secret、机器人能力、应用发布状态与网络。"
            finally:
                if self.process and self.process.returncode is None:
                    self.process.terminate()
                    await self.process.wait()
                self.process = None
            await asyncio.sleep(30)

    async def stop_listener(self):
        self.stopping = True
        if self.listener:
            self.listener.cancel()
            await asyncio.gather(self.listener, return_exceptions=True)
            self.listener = None
        jobs = list(self.jobs)
        for task in jobs:
            task.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        self.workspace = GroupWorkspace(self)
        self.connection = "已停止"

    async def close(self):
        if self.registration:
            self.registration.cancel()
            await asyncio.gather(self.registration, return_exceptions=True)
        await self.stop_listener()

from __future__ import annotations

import asyncio
import tomllib
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .models import SOURCES, Source, SearchRequest
from .recommendations import RecommendationService, RecommendationSettings
from .search import Cache, SearchService
from .sources import Providers, SourceError
from .feishu import FeishuService, Credentials, PushSettings
from .library import LibraryService, REPOSITORY

ROOT = Path(__file__).resolve().parents[1]
LIBRARY_ROOT = ROOT
RECOMMENDATIONS_PATH = ROOT / "data/recommendations.json"
FEISHU_CONFIG_PATH = ROOT / "config/local/feishu.json"
FEISHU_STATE_PATH = ROOT / "data/feishu-deliveries.json"
load_dotenv(ROOT / ".env", override=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(timeout=httpx.Timeout(22, connect=10), follow_redirects=True,
                                 headers={"User-Agent": "PaperTrail/0.1 (local academic search)"}) as client:
        app.state.search = SearchService(Providers(client, os.getenv("OPENALEX_API_KEY", "")), Cache(ROOT / ".cache/search"))
        app.state.recommendations = RecommendationService(app.state.search, RECOMMENDATIONS_PATH)
        app.state.source_recommendations = {
            source: RecommendationService(app.state.search, RECOMMENDATIONS_PATH.parent / "sources" / source / "recommendations.json",
                                          source=source, initial_settings=app.state.recommendations.state.settings)
            for source in SOURCES
        }
        app.state.feishu = FeishuService(client, app.state.search,
            lambda: {"all": app.state.recommendations, **app.state.source_recommendations},
            FEISHU_CONFIG_PATH, FEISHU_STATE_PATH)
        app.state.feishu.start_listener()
        app.state.library = LibraryService(LIBRARY_ROOT, client)
        # One dispatcher serializes daily jobs across workspaces and shares provider limits.
        dispatcher = asyncio.create_task(recommendation_dispatcher(app))
        yield
        dispatcher.cancel()
        await asyncio.gather(dispatcher, return_exceptions=True)
        await app.state.library.close()
        await app.state.feishu.close()
        for service in recommendation_services(app):
            await service.close()
        await app.state.search.close()


def recommendation_services(app):
    return [app.state.recommendations, *app.state.source_recommendations.values()]


async def recommendation_dispatcher(app):
    while True:
        await app.state.library.tick()
        for service in recommendation_services(app):
            if any(s.runner and not s.runner.done() for s in recommendation_services(app)):
                break
            try:
                await service.tick()
            except (SourceError, OSError):
                pass
        try:
            await app.state.feishu.push_ready()
        except (ValueError, OSError):
            app.state.feishu.error = "飞书投递配置或记录不可用，请检查本地文件。"
        await asyncio.sleep(30)


def get_recommendations(request: Request, source: Source | None):
    return request.app.state.source_recommendations[source] if source else request.app.state.recommendations


APP_VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
app = FastAPI(title="PaperTrail", version=APP_VERSION, lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])


@app.middleware("http")
async def local_origin(request: Request, call_next):
    # Block cross-origin sites from driving the local service; Vite uses a same-origin proxy.
    origin = request.headers.get("origin")
    if request.method in ("POST", "DELETE", "PUT", "PATCH") and origin:
        from urllib.parse import urlsplit
        if urlsplit(origin).hostname not in ("127.0.0.1", "localhost"):
            return JSONResponse({"detail": "仅接受本地页面请求"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.2.0", "sources": list(SOURCES),
            "openalex_key_configured": bool(os.getenv("OPENALEX_API_KEY"))}


@app.get("/api/recommendations")
async def recommendations(request: Request, source: Source | None = None):
    return get_recommendations(request, source).overview()


@app.get("/api/feishu")
async def feishu_status(request: Request):
    return request.app.state.feishu.overview()


@app.put("/api/feishu/credentials")
async def feishu_credentials(payload: Credentials, request: Request):
    try:
        return await request.app.state.feishu.save_credentials(payload)
    except (ValueError, OSError):
        raise HTTPException(400, "飞书配置未保存，请检查凭据输入和本地文件权限。") from None


@app.post("/api/feishu/registration")
async def feishu_registration(request: Request):
    try:
        return request.app.state.feishu.begin_registration()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@app.post("/api/feishu/pairing")
async def feishu_pairing(request: Request):
    try:
        return request.app.state.feishu.start_pairing()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@app.delete("/api/feishu/pairing")
async def feishu_unpair(request: Request):
    try:
        return await request.app.state.feishu.unpair()
    except (ValueError, OSError):
        raise HTTPException(400, "解绑失败，请检查本地配置。") from None


@app.put("/api/feishu/push")
async def feishu_push(payload: PushSettings, request: Request):
    try:
        return request.app.state.feishu.save_push(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except OSError:
        raise HTTPException(503, "推送设置未保存，请检查本地文件权限。") from None


@app.put("/api/recommendations/settings")
async def recommendation_settings(payload: RecommendationSettings, request: Request, source: Source | None = None):
    service = get_recommendations(request, source)
    try:
        return service.save_settings(payload)
    except SourceError as exc:
        raise HTTPException(422 if exc.code == "scope" else 503, exc.message) from None
    except OSError:
        raise HTTPException(503, service.storage_error or "配置保存失败") from None


@app.post("/api/recommendations/runs", status_code=202)
async def create_recommendation(request: Request, source: Source | None = None):
    if any(s.runner and not s.runner.done() for s in recommendation_services(request.app)):
        raise HTTPException(409, "已有推荐正在生成（可能来自其他专区），请完成后再试。")
    try:
        return get_recommendations(request, source).start()
    except SourceError as exc:
        raise HTTPException(409 if exc.code == "busy" else 400 if exc.code == "configuration" else 503, exc.message) from None
    except OSError:
        raise HTTPException(503, "无法保存推荐任务，请检查本地文件权限。") from None


@app.get("/api/recommendations/runs/{identifier}")
async def recommendation_run(identifier: str, request: Request, source: Source | None = None):
    run = next((r for r in get_recommendations(request, source).state.runs if r.id == identifier), None)
    if not run:
        raise HTTPException(404, "推荐记录不存在")
    return run.model_dump(exclude={"candidates"})


@app.post("/api/searches", status_code=202)
async def search(payload: SearchRequest, request: Request, source: Source | None = None):
    if source:
        payload = payload.model_copy(update={"sources": [source]})
    try:
        return request.app.state.search.create(payload).snapshot()
    except SourceError as exc:
        raise HTTPException(429, exc.message) from None


def get_task(request: Request, identifier: str):
    task = request.app.state.search.tasks.get(identifier)
    if task is None:
        raise HTTPException(404, "检索任务不存在或已过期，请重新检索。")
    return task


@app.get("/api/searches/{identifier}")
async def snapshot(identifier: str, request: Request):
    return get_task(request, identifier).snapshot()


@app.delete("/api/searches/{identifier}")
async def cancel(identifier: str, request: Request):
    task = get_task(request, identifier)
    await request.app.state.search.cancel(task)
    return task.snapshot()


@app.get("/api/searches/{identifier}/events")
async def events(identifier: str, request: Request):
    task = get_task(request, identifier)

    async def stream():
        version = -1
        while not await request.is_disconnected():
            task.changed.clear()
            if task.revision != version:
                version = task.revision
                yield "event: snapshot\ndata: " + json.dumps(task.snapshot(), ensure_ascii=False) + "\n\n"
            if task.done:
                break
            try:
                await asyncio.wait_for(task.changed.wait(), timeout=10)
            except TimeoutError:
                yield ": keep-alive\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/library")
async def library_status(request: Request):
    return request.app.state.library.overview()


@app.post("/api/library/sync")
async def library_sync(request: Request):
    return request.app.state.library.start()


# Shared presentation, separate local data and scheduler. No private state is served here.
(ROOT / 'data/library').mkdir(parents=True, exist_ok=True)
@app.get('/library/data/terms.json')
async def library_terms():
    return FileResponse(REPOSITORY / 'web/data/terms.json')


app.mount('/library/data', StaticFiles(directory=ROOT / 'data/library'), name='library-data')


app.mount('/library', StaticFiles(directory=REPOSITORY / 'web', html=True), name='library')

DIST = ROOT / "frontend/dist"
if (DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/", include_in_schema=False)
async def index():
    if not (DIST / "index.html").is_file():
        return JSONResponse({"detail": "前端尚未构建。请运行 .\\setup.ps1，或按 README 启动前端开发服务。"}, status_code=503)
    return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})

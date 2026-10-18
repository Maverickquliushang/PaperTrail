"""Run from the project root: uv run --locked python tests/serve_browser.py.

Each launch has fresh recommendation storage; never runs the user's schedule.
"""
import importlib
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
module = importlib.import_module("backend.app")
module.RECOMMENDATIONS_PATH = ROOT / ".tmp" / f"browser-{uuid.uuid4().hex}" / "recommendations.json"
module.FEISHU_CONFIG_PATH = module.RECOMMENDATIONS_PATH.parent / "feishu.json"
module.FEISHU_STATE_PATH = module.RECOMMENDATIONS_PATH.parent / "feishu-deliveries.json"


@module.app.get("/api/validation")
async def validation():
    return {"isolated_recommendations": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(module.app, host="127.0.0.1", port=8765, access_log=False)

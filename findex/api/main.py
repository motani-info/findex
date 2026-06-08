"""FastAPI メインアプリ"""
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from findex.api.routers import dividend, momentum, stock, update, rules, system

app = FastAPI(title="Findex API", version="1.0.0")

# ローカルツールなのでCORS全開
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ルーター登録
app.include_router(dividend.router)
app.include_router(momentum.router)
app.include_router(stock.router)
app.include_router(update.router)
app.include_router(rules.router)
app.include_router(system.router)

# Reactビルド成果物を静的配信（本番起動時）
STATIC_DIR = Path(__file__).parent.parent.parent / "web" / "dist"
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        """SPA用: APIパス以外はindex.htmlを返す"""
        if full_path.startswith("api/"):
            return {"error": "not found"}
        return FileResponse(STATIC_DIR / "index.html")

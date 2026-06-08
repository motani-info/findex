import asyncio
import subprocess
import sys
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/update", tags=["update"])

_update_running = False


@router.get("/status")
def update_status():
    return {"running": _update_running}


@router.post("/run")
async def run_update(dividends: bool = False, quarterly: bool = False):
    """findex update を非同期実行してログをSSEでストリーミング"""
    global _update_running
    if _update_running:
        return {"error": "already running"}

    args = [sys.executable, "-m", "findex"]
    args += ["update"]
    if dividends:
        args += ["--dividends"]
    elif quarterly:
        args += ["--quarterly"]

    async def event_stream():
        global _update_running
        _update_running = True
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd="/Users/motani/Develop/github/findex",
            )
            async for line in proc.stdout:
                text = line.decode("utf-8", errors="replace").rstrip()
                yield f"data: {text}\n\n"
            await proc.wait()
            yield f"data: [完了] exit_code={proc.returncode}\n\n"
        finally:
            _update_running = False

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/stats")
def db_stats():
    from findex.api.db import get_conn
    with get_conn() as conn:
        stock_count = conn.execute("SELECT COUNT(*) FROM stocks").fetchone()[0]
        score_count = conn.execute(
            "SELECT COUNT(DISTINCT code) FROM scores WHERE rowid IN (SELECT MAX(rowid) FROM scores GROUP BY code)"
        ).fetchone()[0]
        last_updated = conn.execute(
            "SELECT MAX(scored_at) FROM scores"
        ).fetchone()[0]
        price_days = conn.execute(
            "SELECT COUNT(DISTINCT date) FROM price_history"
        ).fetchone()[0]
        div_records = conn.execute(
            "SELECT COUNT(*) FROM dividend_history"
        ).fetchone()[0]

    return {
        "stock_count":   stock_count,
        "score_count":   score_count,
        "last_updated":  last_updated[:10] if last_updated else None,
        "price_days":    price_days,
        "div_records":   div_records,
    }

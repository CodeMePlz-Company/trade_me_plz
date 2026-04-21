"""
dashboard/server.py — FastAPI web dashboard

Endpoints:
    GET  /                      → หน้า HTML (dashboard)
    GET  /api/health            → liveness check
    GET  /api/summary           → all-time summary (จาก DB)
    GET  /api/trades            → recent trades (limit query param)
    GET  /api/pnl-by-symbol     → aggregate pnl per symbol
    GET  /api/equity-curve      → time-series สำหรับวาด equity curve
    GET  /api/open-positions    → positions ที่เปิดอยู่ใน session ปัจจุบัน
    GET  /api/config            → config (safe fields เท่านั้น)

Design:
    - อ่านอย่างเดียว — ไม่เขียน DB ผ่าน API (ลดความเสี่ยง)
    - Dashboard poll ทุก 5 วินาที → ไม่ต้องใช้ websocket
    - ใช้ Portfolio(skip_migration=True) — ไม่ re-migrate ทุกครั้งที่ reload
    - Open positions มาจาก Portfolio ที่ inject จาก bot ได้ (เช่น FastAPI state)
      fallback = {} ถ้าไม่มี
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from execution.portfolio import Portfolio, DB_FILE
import config as bot_config


STATIC_DIR = Path(__file__).parent / "static"


def _portfolio(db_path: Optional[str] = None) -> Portfolio:
    """
    สร้าง Portfolio instance อ่านจาก DB
    ใช้ skip_migration=True — dashboard ไม่ควรทำ one-shot CSV import
    """
    return Portfolio(db_path=db_path or DB_FILE, skip_migration=True)


# ==================== Data providers (pure functions) ====================
# แยก business logic จาก FastAPI — test ได้โดยไม่ต้องลง fastapi

def data_health(db_path: Optional[str] = None) -> dict:
    path = db_path or DB_FILE
    return {"status": "ok", "db": path, "db_exists": os.path.exists(path)}


def data_summary(db_path: Optional[str] = None) -> dict:
    return _portfolio(db_path).get_all_time_summary()


def data_trades(db_path: Optional[str] = None,
                limit:   int = 50,
                symbol:  Optional[str] = None,
                action:  Optional[str] = None) -> dict:
    p = _portfolio(db_path)
    rows = p.get_trades(symbol=symbol, action=action, limit=limit)
    return {"count": len(rows), "trades": rows}


def data_pnl_by_symbol(db_path: Optional[str] = None) -> dict:
    return {"symbols": _portfolio(db_path).get_pnl_by_symbol()}


def data_equity_curve(db_path: Optional[str] = None,
                      symbol:  Optional[str] = None,
                      since:   Optional[str] = None) -> dict:
    curve = _portfolio(db_path).get_equity_curve(symbol=symbol, since=since)
    return {"count": len(curve), "points": curve}


def data_open_positions(shared_portfolio: Optional[Portfolio] = None) -> dict:
    if shared_portfolio is None:
        return {"count": 0, "positions": []}
    positions = []
    for sym, d in shared_portfolio.open_trades.items():
        positions.append({
            "symbol":         sym,
            "entry_price":    d.get("price"),
            "amount_crypto":  d.get("amount_crypto"),
            "amount_thb":     d.get("amount_thb"),
        })
    return {"count": len(positions), "positions": positions}


def data_config() -> dict:
    """Expose safe config fields เท่านั้น (ไม่มี API key)"""
    safe = [
        "SYMBOLS", "RESOLUTION",
        "STRATEGY_MODE", "MIN_CONFIDENCE", "MIN_SPREAD_PCT",
        "MAX_POSITION_PCT", "MIN_POSITION_THB",
        "MAX_DAILY_LOSS", "STOP_LOSS_PCT",
        "TAKE_PROFIT_PCT", "TRAILING_STOP_PCT",
        "POSITION_SIZING_MODE", "KELLY_FRACTION",
        "REGIME_ENABLED", "REGIME_BLOCK_BEAR", "REGIME_BLOCK_VOLATILE",
        "MTF_ENABLED",    "MTF_HIGHER_RESOLUTION", "MTF_MODE",
        "SCAN_INTERVAL_SEC", "SIMULATION_MODE",
    ]
    return {k: getattr(bot_config, k, None) for k in safe}


# ==================== FastAPI app factory (lazy import) ====================

def create_app(db_path: Optional[str] = None,
               shared_portfolio: Optional[Portfolio] = None) -> Any:
    """
    Factory — สร้าง FastAPI app

    Parameters:
        db_path          — override DB path (สำหรับ test)
        shared_portfolio — ถ้า bot รันอยู่ในโปรเซสเดียวกันให้ inject
                           เพื่อให้ /api/open-positions เห็น state ปัจจุบัน
    """
    app = FastAPI(
        title="Trade Me Plz — Dashboard",
        version="0.1.0",
        description="Real-time P&L + equity curve จาก SQLite trade log",
    )

    # serve static files (index.html + any JS/CSS)
    if STATIC_DIR.exists():
        app.mount("/static",
                  StaticFiles(directory=str(STATIC_DIR)),
                  name="static")

    # -------------- Root --------------

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        index_html = STATIC_DIR / "index.html"
        if not index_html.exists():
            return HTMLResponse(
                "<h1>dashboard/static/index.html ไม่พบ</h1>",
                status_code=500,
            )
        return HTMLResponse(index_html.read_text(encoding="utf-8"))

    # -------------- Health --------------

    @app.get("/api/health")
    def health() -> dict:
        path = db_path or DB_FILE
        return {
            "status":  "ok",
            "db":      path,
            "db_exists": os.path.exists(path),
        }

    # -------------- Summary --------------

    @app.get("/api/summary")
    def summary() -> dict:
        p = _portfolio(db_path)
        return p.get_all_time_summary()

    # -------------- Recent trades --------------

    @app.get("/api/trades")
    def trades(
        limit:  int           = Query(50, ge=1, le=500),
        symbol: Optional[str] = Query(None),
        action: Optional[str] = Query(None,
                                      pattern="^(buy|sell)$"),
    ) -> dict:
        p = _portfolio(db_path)
        rows = p.get_trades(symbol=symbol, action=action, limit=limit)
        return {"count": len(rows), "trades": rows}

    # -------------- P&L by symbol --------------

    @app.get("/api/pnl-by-symbol")
    def pnl_by_symbol() -> dict:
        p = _portfolio(db_path)
        rows = p.get_pnl_by_symbol()
        return {"symbols": rows}

    # -------------- Equity curve --------------

    @app.get("/api/equity-curve")
    def equity_curve(
        symbol: Optional[str] = Query(None),
        since:  Optional[str] = Query(None,
            description="ISO timestamp e.g. 2025-01-01T00:00:00"),
    ) -> dict:
        p = _portfolio(db_path)
        curve = p.get_equity_curve(symbol=symbol, since=since)
        return {"count": len(curve), "points": curve}

    # -------------- Open positions --------------

    @app.get("/api/open-positions")
    def open_positions() -> dict:
        """
        ถ้า bot inject shared_portfolio → เห็น open_trades จริง
        ไม่งั้น return []
        """
        if shared_portfolio is None:
            return {"count": 0, "positions": []}
        positions = []
        for sym, data in shared_portfolio.open_trades.items():
            positions.append({
                "symbol":         sym,
                "entry_price":    data.get("price"),
                "amount_crypto":  data.get("amount_crypto"),
                "amount_thb":     data.get("amount_thb"),
            })
        return {"count": len(positions), "positions": positions}

    # -------------- Config snapshot --------------

    @app.get("/api/config")
    def config_info() -> dict:
        """Expose safe config fields เท่านั้น (ไม่มี API key)"""
        safe = [
            "SYMBOLS", "RESOLUTION",
            "STRATEGY_MODE", "MIN_CONFIDENCE", "MIN_SPREAD_PCT",
            "MAX_POSITION_PCT", "MIN_POSITION_THB",
            "MAX_DAILY_LOSS", "STOP_LOSS_PCT",
            "TAKE_PROFIT_PCT", "TRAILING_STOP_PCT",
            "POSITION_SIZING_MODE", "KELLY_FRACTION",
            "REGIME_ENABLED", "REGIME_BLOCK_BEAR", "REGIME_BLOCK_VOLATILE",
            "MTF_ENABLED",    "MTF_HIGHER_RESOLUTION", "MTF_MODE",
            "SCAN_INTERVAL_SEC", "SIMULATION_MODE",
        ]
        return {k: getattr(bot_config, k, None) for k in safe}

    return app


# default instance สำหรับ `uvicorn dashboard.server:app`
app = create_app()


def main() -> None:
    """รันเซิร์ฟเวอร์ด้วย uvicorn"""
    try:
        import uvicorn
    except ImportError as e:
        raise RuntimeError("pip install uvicorn ก่อน") from e

    host = os.getenv("DASHBOARD_HOST", "127.0.0.1")
    port = int(os.getenv("DASHBOARD_PORT", 8000))
    print(f"[DASHBOARD] http://{host}:{port}")
    uvicorn.run("dashboard.server:app",
                host=host, port=port, reload=False)


if __name__ == "__main__":
    main()

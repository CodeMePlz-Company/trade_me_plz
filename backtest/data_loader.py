"""
data_loader.py — โหลด / cache OHLCV ย้อนหลังจาก Bitkub
                 + สร้าง synthetic data สำหรับ offline testing

Candle format (ตามที่ data/rest_client.py ใช้):
    {"time": unix_ts, "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}
"""
import os
import csv
import math
import random
import time
import requests
from pathlib import Path
from typing import Literal

BASE_URL  = "https://api.bitkub.com"
CACHE_DIR = Path(__file__).resolve().parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)

# Bitkub API จำกัด ~1000 bars ต่อ request (approx) — เราจะขอทีละก้อน
MAX_BARS_PER_REQUEST = 1000


# ========== Bitkub API ==========

def _fetch_chunk(symbol: str, resolution: str,
                 ts_from: int, ts_to: int) -> list[dict]:
    """ดึง candles หนึ่งก้อนจาก Bitkub TradingView endpoint"""
    r = requests.get(
        f"{BASE_URL}/tradingview/history",
        params={
            "symbol":     f"{symbol.split('_')[0]}_THB",
            "resolution": resolution,
            "from":       ts_from,
            "to":         ts_to,
        },
        timeout=15,
    )
    data = r.json()
    if data.get("s") != "ok":
        return []

    return [
        {
            "time":   data["t"][i],
            "open":   data["o"][i],
            "high":   data["h"][i],
            "low":    data["l"][i],
            "close":  data["c"][i],
            "volume": data["v"][i],
        }
        for i in range(len(data["t"]))
    ]


def fetch_historical(symbol: str,
                     resolution: str = "60",
                     days: int = 90) -> list[dict]:
    """
    ดึงข้อมูลย้อนหลังจำนวน `days` วัน จาก Bitkub
    แบ่งเป็นหลาย request ถ้ายาวเกิน

    resolution: "1","5","15","60","240","1D"
    """
    ts_to   = int(time.time())
    ts_from = ts_to - days * 86400

    # คำนวณจำนวนบาร์ทั้งหมด (โดยประมาณ)
    bar_sec = 86400 if resolution == "1D" else int(resolution) * 60
    total_bars = (ts_to - ts_from) // bar_sec

    print(f"[DATA] ดึง {symbol} resolution={resolution} ~{total_bars} bars "
          f"({days} วัน)")

    all_candles: list[dict] = []
    cur_from = ts_from

    while cur_from < ts_to:
        chunk_to = min(cur_from + bar_sec * MAX_BARS_PER_REQUEST, ts_to)
        chunk = _fetch_chunk(symbol, resolution, cur_from, chunk_to)

        if not chunk:
            break
        all_candles.extend(chunk)

        # กัน duplicate: step ไปข้างหน้าจาก bar สุดท้าย
        cur_from = chunk[-1]["time"] + bar_sec
        time.sleep(0.2)    # ให้เกียรติ rate limit

    # dedupe ตาม time
    seen = set()
    deduped = []
    for c in all_candles:
        if c["time"] not in seen:
            seen.add(c["time"])
            deduped.append(c)

    deduped.sort(key=lambda c: c["time"])
    print(f"[DATA] ได้ {len(deduped)} bars")
    return deduped


# ========== CSV cache ==========

def _cache_path(symbol: str, resolution: str) -> Path:
    return CACHE_DIR / f"{symbol}_{resolution}.csv"


def save_csv(candles: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "time", "open", "high", "low", "close", "volume"
        ])
        writer.writeheader()
        writer.writerows(candles)
    print(f"[CACHE] บันทึก {len(candles)} bars → {path.name}")


def load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path) as f:
        reader = csv.DictReader(f)
        return [
            {
                "time":   int(row["time"]),
                "open":   float(row["open"]),
                "high":   float(row["high"]),
                "low":    float(row["low"]),
                "close":  float(row["close"]),
                "volume": float(row["volume"]),
            }
            for row in reader
        ]


def get_or_fetch(symbol: str,
                 resolution: str = "60",
                 days: int = 90,
                 use_cache: bool = True) -> list[dict]:
    """
    โหลดจาก cache ถ้ามี ไม่งั้น fetch จาก API แล้วเก็บ cache
    """
    path = _cache_path(symbol, resolution)

    if use_cache and path.exists():
        cached = load_csv(path)
        if cached:
            print(f"[CACHE] ใช้ cache เดิม ({len(cached)} bars) → {path.name}")
            return cached

    candles = fetch_historical(symbol, resolution, days)
    if candles:
        save_csv(candles, path)
    return candles


# ========== Synthetic data (สำหรับทดสอบ offline) ==========

def generate_synthetic(
    n_bars:      int = 500,
    start_price: float = 1_000_000,
    regime:      Literal["uptrend", "downtrend", "sideways", "volatile"] = "uptrend",
    seed:        int = 42,
) -> list[dict]:
    """
    สร้าง OHLCV ปลอมสำหรับทดสอบ backtest
    เมื่อไม่มีเน็ต หรือ อยากควบคุม market regime

    regime:
        uptrend    — ขาขึ้น +0.1% ต่อ bar เฉลี่ย
        downtrend  — ขาลง -0.1% ต่อ bar เฉลี่ย
        sideways   — ไม่มีแนวโน้ม
        volatile   — noise เยอะ
    """
    random.seed(seed)

    drift = {"uptrend": 0.001, "downtrend": -0.001,
             "sideways": 0.0,  "volatile":  0.0}[regime]
    vol   = {"uptrend": 0.008, "downtrend": 0.008,
             "sideways": 0.006, "volatile":  0.025}[regime]

    candles = []
    price   = start_price
    ts      = int(time.time()) - n_bars * 3600     # 1H bars

    for i in range(n_bars):
        # geometric Brownian motion step
        ret   = drift + random.gauss(0, vol)
        price = max(price * (1 + ret), 1.0)

        # สร้าง OHLC รอบราคาปิด
        high  = price * (1 + abs(random.gauss(0, vol / 2)))
        low   = price * (1 - abs(random.gauss(0, vol / 2)))
        open_ = price * (1 + random.gauss(0, vol / 4))

        candles.append({
            "time":   ts + i * 3600,
            "open":   round(open_, 2),
            "high":   round(high, 2),
            "low":    round(low, 2),
            "close":  round(price, 2),
            "volume": round(random.uniform(10, 100), 4),
        })

    return candles


# ========== Quick test ==========

if __name__ == "__main__":
    print("\n▶ Synthetic (uptrend, 100 bars)")
    data = generate_synthetic(n_bars=100, regime="uptrend")
    print(f"  bars = {len(data)}")
    print(f"  first close = {data[0]['close']:,.2f}")
    print(f"  last close  = {data[-1]['close']:,.2f}")
    pct = (data[-1]['close'] / data[0]['close'] - 1) * 100
    print(f"  change      = {pct:+.1f}%")

    print("\n▶ Synthetic (downtrend, 100 bars)")
    data = generate_synthetic(n_bars=100, regime="downtrend", seed=1)
    pct = (data[-1]['close'] / data[0]['close'] - 1) * 100
    print(f"  change      = {pct:+.1f}%")

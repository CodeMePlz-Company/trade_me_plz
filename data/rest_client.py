import requests
import time

BASE_URL = "https://api.bitkub.com"

def get_server_time() -> int:
    """ดึงเวลา server (ใช้สร้าง timestamp สำหรับ auth)"""
    r = requests.get(f"{BASE_URL}/api/v3/servertime")
    return r.json()["result"]

def get_ticker(symbol: str = "BTC_THB") -> dict:
    """
    ราคาปัจจุบันของ coin คู่นึง
    ได้: last, highestBid, lowestAsk, percentChange, volume
    """
    r = requests.get(f"{BASE_URL}/api/market/ticker", params={"sym": symbol})
    data = r.json()
    return data.get(symbol, {})

def get_all_tickers() -> dict:
    """ราคาทุก coin — ใช้สำหรับ Spread Scanner ในชั้น 2"""
    r = requests.get(f"{BASE_URL}/api/market/ticker")
    return r.json() if r.ok else {}

def get_order_book(symbol: str = "BTC_THB", limit: int = 10) -> dict:
    """
    Order book (bid/ask list)
    ใช้ดูว่ามีคนรอซื้อ/ขายที่ราคาไหน
    """
    r = requests.get(
        f"{BASE_URL}/api/market/books",
        params={"sym": symbol, "lmt": limit}
    )
    result = r.json().get("result", {})
    bids = result.get("bids", [])  # [[price, volume, value], ...]
    asks = result.get("asks", [])
    return {"bids": bids, "asks": asks}

def get_recent_trades(symbol: str = "BTC_THB", limit: int = 20) -> list:
    """
    รายการเทรดล่าสุด
    ได้: timestamp, rate, amount, side (BUY/SELL)
    """
    r = requests.get(
        f"{BASE_URL}/api/market/trades",
        params={"sym": symbol, "lmt": limit}
    )
    return r.json().get("result", [])

def get_ohlcv(symbol: str = "BTC_THB", resolution: str = "60", limit: int = 100) -> dict:
    """
    แท่งเทียน OHLCV สำหรับ Technical Indicators ในชั้น 2
    resolution: 1, 5, 15, 60, 240, 1D (นาที)
    """
    ts_to   = int(time.time())
    ts_from = ts_to - (int(resolution) * 60 * limit)

    r = requests.get(
        f"{BASE_URL}/tradingview/history",
        params={
            "symbol": f"{symbol.split('_')[0]}_THB",
            "resolution": resolution,
            "from": ts_from,
            "to": ts_to
        }
    )
    data = r.json()
    if data.get("s") != "ok":
        return {}

    # แปลงเป็น dict list ให้ใช้งานง่าย
    candles = []
    for i in range(len(data["t"])):
        candles.append({
            "time":   data["t"][i],
            "open":   data["o"][i],
            "high":   data["h"][i],
            "low":    data["l"][i],
            "close":  data["c"][i],
            "volume": data["v"][i],
        })
    return candles

# ---- Quick test ----
if __name__ == "__main__":
    print("Server time:", get_server_time())

    btc = get_ticker("BTC_THB")
    print(f"BTC: last={btc.get('last')} bid={btc.get('highestBid')} ask={btc.get('lowestAsk')}")

    book = get_order_book("BTC_THB", limit=3)
    print("Top 3 bids:", book["bids"][:3])
    print("Top 3 asks:", book["asks"][:3])

    candles = get_ohlcv("BTC_THB", resolution="60", limit=5)
    print("Last 5 candles:", candles[-5:] if candles else "ไม่มีข้อมูล")
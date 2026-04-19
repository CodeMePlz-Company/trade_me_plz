import requests
import hashlib
import hmac
import json
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY    = os.getenv("API_KEY", "")
API_SECRET = os.getenv("API_SECRET", "")
BASE_URL   = "https://api.bitkub.com"

def _get_timestamp() -> int:
    r = requests.get(f"{BASE_URL}/api/v3/servertime")
    return r.json()["result"]

def _sign(api_secret: str, payload: dict) -> str:
    payload_str = json.dumps(payload, separators=(",", ":"))
    return hmac.new(
        api_secret.encode(),
        payload_str.encode(),
        hashlib.sha256
    ).hexdigest()

def _post(endpoint: str, payload: dict) -> dict:
    """ส่ง signed POST request"""
    ts = _get_timestamp()
    payload["ts"] = ts
    payload["sig"] = _sign(API_SECRET, payload)

    headers = {"X-BTK-APIKEY": API_KEY, "Content-Type": "application/json"}
    r = requests.post(f"{BASE_URL}{endpoint}", json=payload, headers=headers)
    return r.json()

# ========== Balance ==========

def get_balances() -> dict:
    """ดึงยอดเงินทั้งหมด"""
    result = _post("/api/v3/market/balances", {})
    return result.get("result", {})

def get_thb_balance() -> float:
    """ดึงยอด THB ที่ใช้ได้"""
    balances = get_balances()
    return float(balances.get("THB", {}).get("available", 0))

def get_crypto_balance(symbol: str) -> float:
    """ดึงยอด crypto เช่น BTC, ETH"""
    coin = symbol.split("_")[0]
    balances = get_balances()
    return float(balances.get(coin, {}).get("available", 0))

# ========== Place Orders ==========

def place_buy_market(symbol: str, amount_thb: float) -> dict:
    """
    ซื้อแบบ market order
    amount_thb = จำนวน THB ที่จะใช้ซื้อ
    """
    payload = {
        "sym": symbol,
        "amt": amount_thb,
        "rat": 0,
        "typ": "market",
    }
    result = _post("/api/v3/market/place-bid", payload)
    print(f"[ORDER] BUY  {symbol} {amount_thb} THB → {result}")
    return result

def place_buy_limit(symbol: str, amount_thb: float, rate: float) -> dict:
    """
    ซื้อแบบ limit order
    rate = ราคาที่ต้องการซื้อ
    """
    payload = {
        "sym": symbol,
        "amt": amount_thb,
        "rat": rate,
        "typ": "limit",
    }
    result = _post("/api/v3/market/place-bid", payload)
    print(f"[ORDER] BUY  LIMIT {symbol} @ {rate:,} THB → {result}")
    return result

def place_sell_market(symbol: str, amount_crypto: float) -> dict:
    """
    ขายแบบ market order
    amount_crypto = จำนวน crypto ที่จะขาย
    """
    payload = {
        "sym": symbol,
        "amt": amount_crypto,
        "rat": 0,
        "typ": "market",
    }
    result = _post("/api/v3/market/place-ask", payload)
    print(f"[ORDER] SELL {symbol} {amount_crypto} → {result}")
    return result

def place_sell_limit(symbol: str, amount_crypto: float, rate: float) -> dict:
    """
    ขายแบบ limit order
    rate = ราคาที่ต้องการขาย
    """
    payload = {
        "sym": symbol,
        "amt": amount_crypto,
        "rat": rate,
        "typ": "limit",
    }
    result = _post("/api/v3/market/place-ask", payload)
    print(f"[ORDER] SELL LIMIT {symbol} @ {rate:,} THB → {result}")
    return result

def cancel_order(symbol: str, order_id: str,
                 side: str = "buy") -> dict:
    """ยกเลิก order ที่ค้างอยู่"""
    payload = {
        "sym": symbol,
        "id":  order_id,
        "sd":  side,
    }
    result = _post("/api/v3/market/cancel-order", payload)
    print(f"[ORDER] CANCEL {symbol} #{order_id} → {result}")
    return result

def get_open_orders(symbol: str) -> list:
    """ดึง orders ที่ยังไม่ execute"""
    payload = {"sym": symbol}
    result  = _post("/api/v3/market/my-open-orders", payload)
    return result.get("result", [])
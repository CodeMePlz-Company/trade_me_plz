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

# ========== Auth V3 ==========

def _get_timestamp() -> str:
    """timestamp เป็น millisecond (string)"""
    r = requests.get(f"{BASE_URL}/api/v3/servertime")
    return str(r.json()["result"])

def _sign(timestamp: str, method: str,
          path: str, body: str = "") -> str:
    """
    V3 signature = HMAC-SHA256 ของ
    timestamp + METHOD + /api/path + body
    """
    payload = timestamp + method.upper() + path + body
    return hmac.new(
        API_SECRET.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()

def _get_headers(timestamp: str, signature: str) -> dict:
    return {
        "X-BTK-APIKEY":    API_KEY,
        "X-BTK-TIMESTAMP": timestamp,
        "X-BTK-SIGN":      signature,
        "Content-Type":    "application/json",
    }

def _post(path: str, body: dict) -> dict:
    """POST request พร้อม V3 auth"""
    ts       = _get_timestamp()
    body_str = json.dumps(body, separators=(",", ":"))
    sig      = _sign(ts, "POST", path, body_str)
    headers  = _get_headers(ts, sig)

    r = requests.post(f"{BASE_URL}{path}",
                      data=body_str, headers=headers)
    return r.json()

def _get_secure(path: str, params: dict = {}) -> dict:
    """GET request พร้อม V3 auth"""
    ts  = _get_timestamp()

    # query string ต้องรวมใน signature
    qs  = "&".join(f"{k}={v}" for k, v in params.items())
    full_path = f"{path}?{qs}" if qs else path
    sig = _sign(ts, "GET", full_path)
    headers = _get_headers(ts, sig)

    r = requests.get(f"{BASE_URL}{full_path}", headers=headers)
    return r.json()

# ========== Balance ==========

def get_balances() -> dict:
    result = _post("/api/v3/market/balances", {})
    return result.get("result", {})

def get_thb_balance() -> float:
    balances = get_balances()
    return float(balances.get("THB", {}).get("available", 0))

def get_crypto_balance(symbol: str) -> float:
    coin = symbol.split("_")[0]
    balances = get_balances()
    return float(balances.get(coin, {}).get("available", 0))

# ========== Place Orders ==========

def place_buy_market(symbol: str, amount_thb: float) -> dict:
    body = {
        "sym": symbol,
        "amt": amount_thb,
        "rat": 0,
        "typ": "market",
    }
    result = _post("/api/v3/market/place-bid", body)
    print(f"[ORDER] BUY  {symbol} {amount_thb} THB → {result}")
    return result

def place_buy_limit(symbol: str,
                    amount_thb: float, rate: float) -> dict:
    body = {
        "sym": symbol,
        "amt": amount_thb,
        "rat": rate,
        "typ": "limit",
    }
    result = _post("/api/v3/market/place-bid", body)
    print(f"[ORDER] BUY LIMIT {symbol} @ {rate:,} → {result}")
    return result

def place_sell_market(symbol: str,
                      amount_crypto: float) -> dict:
    body = {
        "sym": symbol,
        "amt": amount_crypto,
        "rat": 0,
        "typ": "market",
    }
    result = _post("/api/v3/market/place-ask", body)
    print(f"[ORDER] SELL {symbol} {amount_crypto} → {result}")
    return result

def place_sell_limit(symbol: str,
                     amount_crypto: float, rate: float) -> dict:
    body = {
        "sym": symbol,
        "amt": amount_crypto,
        "rat": rate,
        "typ": "limit",
    }
    result = _post("/api/v3/market/place-ask", body)
    print(f"[ORDER] SELL LIMIT {symbol} @ {rate:,} → {result}")
    return result

def cancel_order(symbol: str, order_id: str,
                 side: str = "buy") -> dict:
    body = {
        "sym": symbol,
        "id":  order_id,
        "sd":  side,
    }
    result = _post("/api/v3/market/cancel-order", body)
    print(f"[ORDER] CANCEL {symbol} #{order_id} → {result}")
    return result

def get_open_orders(symbol: str) -> list:
    result = _get_secure("/api/v3/market/my-open-orders",
                         {"sym": symbol})
    return result.get("result", [])

# ========== Quick test ==========

if __name__ == "__main__":
    print("THB balance:", get_thb_balance())
    print("BTC balance:", get_crypto_balance("BTC_THB"))
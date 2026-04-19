import json
import threading
import websocket
from datetime import datetime

BASE_WS = "wss://api.bitkub.com/websocket-api"

class BitkubWebSocket:
    """
    รับ real-time data จาก Bitkub WebSocket
    รองรับ: ticker, trade, orderbook
    """

    def __init__(self, symbols: list = ["thb_btc"], on_tick=None, on_trade=None):
        self.symbols  = symbols
        self.on_tick  = on_tick    # callback เมื่อราคาเปลี่ยน
        self.on_trade = on_trade   # callback เมื่อมีการเทรดเกิดขึ้น
        self.ws       = None
        self.running  = False
        self.latest   = {}         # เก็บราคาล่าสุดของแต่ละ symbol

    def _build_stream_url(self) -> str:
        """สร้าง URL รวม streams หลายตัว"""
        streams = []
        for sym in self.symbols:
            streams.append(f"market.ticker.{sym}")
            streams.append(f"market.trade.{sym}")
        return f"{BASE_WS}/{','.join(streams)}"

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            stream = data.get("stream", "")

            if "ticker" in stream:
                symbol = stream.split(".")[-1].upper()
                tick = {
                    "symbol":  symbol,
                    "last":    data.get("last"),
                    "bid":     data.get("highestBid"),
                    "ask":     data.get("lowestAsk"),
                    "change":  data.get("percentChange"),
                    "volume":  data.get("baseVolume"),
                    "time":    datetime.now().isoformat(),
                }
                self.latest[symbol] = tick

                if self.on_tick:
                    self.on_tick(tick)

            elif "trade" in stream:
                symbol = stream.split(".")[-1].upper()
                # data["data"][0] = trades array
                trades_raw = data.get("data", [[]])[0]
                for t in trades_raw:
                    trade = {
                        "symbol": symbol,
                        "time":   t[0],
                        "rate":   t[1],
                        "amount": t[2],
                        "side":   t[3],  # BUY / SELL
                    }
                    if self.on_trade:
                        self.on_trade(trade)

        except Exception as e:
            print(f"[WS] parse error: {e}")

    def _on_error(self, ws, error):
        print(f"[WS] error: {error}")

    def _on_close(self, ws, *args):
        print("[WS] connection closed")
        if self.running:
            print("[WS] reconnecting in 5s...")
            threading.Timer(5, self.start).start()

    def _on_open(self, ws):
        print(f"[WS] connected — streaming: {self.symbols}")

    def start(self):
        """เริ่ม WebSocket ใน background thread"""
        self.running = True
        url = self._build_stream_url()
        self.ws = websocket.WebSocketApp(
            url,
            on_message = self._on_message,
            on_error   = self._on_error,
            on_close   = self._on_close,
            on_open    = self._on_open,
        )
        t = threading.Thread(target=self.ws.run_forever, daemon=True)
        t.start()

    def stop(self):
        self.running = False
        if self.ws:
            self.ws.close()

    def get_latest(self, symbol: str) -> dict:
        """ดึงราคาล่าสุดของ symbol ที่ต้องการ"""
        return self.latest.get(symbol.upper(), {})


# ---- Quick test ----
if __name__ == "__main__":
    def on_tick(tick):
        print(f"[TICK] {tick['symbol']} last={tick['last']} bid={tick['bid']} ask={tick['ask']}")

    def on_trade(trade):
        print(f"[TRADE] {trade['symbol']} {trade['side']} {trade['amount']} @ {trade['rate']}")

    ws = BitkubWebSocket(
        symbols  = ["thb_btc", "thb_eth", "thb_xrp"],
        on_tick  = on_tick,
        on_trade = on_trade,
    )
    ws.start()

    import time
    time.sleep(30)  # ดูข้อมูล 30 วินาที
    ws.stop()
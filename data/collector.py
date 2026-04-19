import time
import threading
from data.rest_client import get_all_tickers, get_order_book, get_ohlcv
from data.ws_feed import BitkubWebSocket
from data.webhook_receiver import signal_queue

class DataCollector:
    """
    รวม data จากทุกแหล่งไว้ที่เดียว
    ชั้น Brain จะดึงข้อมูลจาก collector นี้
    """

    def __init__(self, symbols: list = ["BTC_THB", "ETH_THB", "XRP_THB"]):
        self.symbols  = symbols
        self.ws_syms  = [s.replace("_", "").lower().replace("thb", "thb_").replace("thb_", "thb_")
                         for s in symbols]
        # แปลง BTC_THB → thb_btc
        self.ws_syms  = ["thb_" + s.split("_")[0].lower() for s in symbols]

        self.ws = BitkubWebSocket(
            symbols  = self.ws_syms,
            on_tick  = self._on_tick,
            on_trade = self._on_trade,
        )

        self.tickers    = {}   # ราคาล่าสุดทุก coin
        self.order_books = {}  # order book ของแต่ละ symbol
        self.candles    = {}   # OHLCV
        self.trades     = []   # recent trades จาก WS

    def _on_tick(self, tick):
        sym = tick["symbol"]
        self.tickers[sym] = tick

    def _on_trade(self, trade):
        self.trades.append(trade)
        if len(self.trades) > 500:
            self.trades = self.trades[-500:]

    def _refresh_rest(self):
        """ดึง REST data ทุก 30 วินาที"""
        while True:
            try:
                # Order books
                for sym in self.symbols:
                    self.order_books[sym] = get_order_book(sym, limit=10)

                # OHLCV สำหรับ indicators
                for sym in self.symbols:
                    self.candles[sym] = get_ohlcv(sym, resolution="60", limit=100)

                print(f"[COLLECTOR] REST refreshed — {len(self.symbols)} symbols")
            except Exception as e:
                print(f"[COLLECTOR] REST error: {e}")
            time.sleep(30)

    def start(self):
        """เริ่ม WebSocket + REST refresh loop"""
        self.ws.start()

        t = threading.Thread(target=self._refresh_rest, daemon=True)
        t.start()
        print("[COLLECTOR] started")

    def get_snapshot(self, symbol: str) -> dict:
        """ดึงภาพรวมข้อมูลของ symbol หนึ่งตัว"""
        ws_sym = "THB_" + symbol.split("_")[0]
        return {
            "ticker":     self.tickers.get(ws_sym, {}),
            "order_book": self.order_books.get(symbol, {}),
            "candles":    self.candles.get(symbol, []),
            "signals":    signal_queue[-5:],  # TradingView signals ล่าสุด
        }


# ---- Quick test ----
if __name__ == "__main__":
    collector = DataCollector(["BTC_THB", "ETH_THB"])
    collector.start()

    time.sleep(10)

    snap = collector.get_snapshot("BTC_THB")
    print("Ticker:", snap["ticker"])
    print("Order book bids:", snap["order_book"].get("bids", [])[:3])
    print("Candles count:", len(snap["candles"]))
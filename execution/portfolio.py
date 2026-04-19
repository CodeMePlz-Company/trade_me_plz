import csv
import os
from datetime import datetime
from dataclasses import dataclass, asdict

LOG_FILE = "logs/trades.csv"

@dataclass
class TradeRecord:
    timestamp:  str
    symbol:     str
    action:     str   # buy / sell
    price:      float
    amount_thb: float
    amount_crypto: float
    fee:        float
    pnl:        float   # กำไร/ขาดทุน (คำนวณเมื่อขาย)
    balance_after: float

class Portfolio:
    """
    ติดตาม P&L และบันทึกประวัติการเทรดทั้งหมด
    """

    def __init__(self):
        self.trades:      list[TradeRecord] = []
        self.open_trades: dict = {}   # symbol → {price, amount_crypto, amount_thb}
        self._ensure_log_file()

    def _ensure_log_file(self):
        os.makedirs("logs", exist_ok=True)
        if not os.path.exists(LOG_FILE):
            with open(LOG_FILE, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "timestamp", "symbol", "action", "price",
                    "amount_thb", "amount_crypto", "fee", "pnl", "balance_after"
                ])
                writer.writeheader()

    def record_buy(self, symbol: str, price: float,
                   amount_thb: float, fee: float, balance_after: float):
        """บันทึกการซื้อ"""
        amount_crypto = (amount_thb - fee) / price if price > 0 else 0

        self.open_trades[symbol] = {
            "price":          price,
            "amount_crypto":  amount_crypto,
            "amount_thb":     amount_thb,
        }

        record = TradeRecord(
            timestamp     = datetime.now().isoformat(),
            symbol        = symbol,
            action        = "buy",
            price         = price,
            amount_thb    = amount_thb,
            amount_crypto = amount_crypto,
            fee           = fee,
            pnl           = 0.0,
            balance_after = balance_after,
        )
        self.trades.append(record)
        self._write_log(record)
        print(f"[PORTFOLIO] BUY  {symbol} {amount_crypto:.8f} @ {price:,}")

    def record_sell(self, symbol: str, price: float,
                    amount_crypto: float, fee: float, balance_after: float):
        """บันทึกการขาย + คำนวณ P&L"""
        open_trade = self.open_trades.pop(symbol, None)
        pnl = 0.0

        if open_trade:
            revenue   = amount_crypto * price - fee
            cost      = open_trade["amount_thb"]
            pnl       = round(revenue - cost, 4)

        record = TradeRecord(
            timestamp     = datetime.now().isoformat(),
            symbol        = symbol,
            action        = "sell",
            price         = price,
            amount_thb    = amount_crypto * price,
            amount_crypto = amount_crypto,
            fee           = fee,
            pnl           = pnl,
            balance_after = balance_after,
        )
        self.trades.append(record)
        self._write_log(record)

        emoji = "+" if pnl >= 0 else "-"
        print(f"[PORTFOLIO] SELL {symbol} P&L={emoji}{abs(pnl):.2f} THB")
        return pnl

    def _write_log(self, record: TradeRecord):
        with open(LOG_FILE, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=asdict(record).keys())
            writer.writerow(asdict(record))

    def get_summary(self) -> dict:
        """สรุปผลการเทรดทั้งหมด"""
        sells       = [t for t in self.trades if t.action == "sell"]
        total_pnl   = sum(t.pnl for t in sells)
        wins        = [t for t in sells if t.pnl > 0]
        losses      = [t for t in sells if t.pnl < 0]
        win_rate    = len(wins) / len(sells) * 100 if sells else 0

        return {
            "total_trades": len(self.trades),
            "total_sells":  len(sells),
            "wins":         len(wins),
            "losses":       len(losses),
            "win_rate":     round(win_rate, 1),
            "total_pnl":    round(total_pnl, 2),
            "best_trade":   max((t.pnl for t in sells), default=0),
            "worst_trade":  min((t.pnl for t in sells), default=0),
            "open_positions": list(self.open_trades.keys()),
        }

    def print_summary(self):
        s = self.get_summary()
        print("\n" + "=" * 40)
        print(f"  รวมเทรด   : {s['total_trades']} ครั้ง")
        print(f"  Win rate  : {s['win_rate']}%  ({s['wins']}W / {s['losses']}L)")
        print(f"  P&L รวม   : {s['total_pnl']:+.2f} THB")
        print(f"  กำไรสูงสุด: {s['best_trade']:+.2f} THB")
        print(f"  ขาดทุนสูงสุด: {s['worst_trade']:+.2f} THB")
        print(f"  Open      : {s['open_positions']}")
        print("=" * 40)
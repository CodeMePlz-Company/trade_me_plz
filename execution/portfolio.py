"""
portfolio.py — SQLite-backed trade log + P&L tracker

เก็บประวัติเทรดใน SQLite (logs/trades.db) เพื่อให้ query/รายงานสะดวก:
    - Aggregate stats ต่อ symbol
    - Profit factor / expectancy / avg win/loss
    - Filter ตาม date range / action / symbol
    - Migration อัตโนมัติจาก logs/trades.csv เก่า (ถ้ามี)

Public API (backward-compat):
    record_buy(symbol, price, amount_thb, fee, balance_after)
    record_sell(symbol, price, amount_crypto, fee, balance_after) → pnl
    get_summary() → dict   (stats ของ session ปัจจุบัน — ดู in-memory self.trades)
    print_summary()

ฟังก์ชันใหม่ที่ SQLite เปิดให้ใช้:
    get_trades(symbol=None, action=None, since=None, limit=None) → list[dict]
    get_pnl_by_symbol() → list[dict]
    get_all_time_summary()  → dict (คำนวณจาก DB — อิงทั้งหมดที่เคยบันทึก)
    export_csv(path)        → int  (จำนวน rows ที่ export)
    load_from_db()          → None (โหลด trades ทั้งหมดกลับเข้า self.trades)

Design choices:
    - self.trades + get_summary() = session-scope (in-memory) — เหมือน CSV เดิม
    - DB = persistent all-time log สำหรับรายงาน/analytics
    - db_path รับเป็น arg ได้ เพื่อให้ test แยกกันได้ (default = logs/trades.db)
"""
import csv
import os
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional

# backward-compat: LOG_FILE ยังคงชี้ไปไฟล์เดียวกับ DB_FILE
DB_FILE  = "logs/trades.db"
LOG_FILE = DB_FILE   # alias — code เก่าที่ import LOG_FILE ยังใช้งานได้

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    action          TEXT    NOT NULL CHECK (action IN ('buy', 'sell')),
    price           REAL    NOT NULL,
    amount_thb      REAL    NOT NULL,
    amount_crypto   REAL    NOT NULL,
    fee             REAL    NOT NULL DEFAULT 0,
    pnl             REAL    NOT NULL DEFAULT 0,
    balance_after   REAL    NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_symbol       ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_action       ON trades(action);
CREATE INDEX IF NOT EXISTS idx_symbol_action ON trades(symbol, action);
CREATE INDEX IF NOT EXISTS idx_timestamp    ON trades(timestamp);
"""


@dataclass
class TradeRecord:
    timestamp:     str
    symbol:        str
    action:        str     # "buy" / "sell"
    price:         float
    amount_thb:    float
    amount_crypto: float
    fee:           float
    pnl:           float   # กำไร/ขาดทุน (คำนวณตอน sell)
    balance_after: float


class Portfolio:
    """
    ติดตาม P&L + บันทึกประวัติการเทรดลง SQLite

    Parameters:
        db_path — path ของ SQLite file (default "logs/trades.db")
                  ให้ test ใช้ path แยกต่อกันได้
        skip_migration — ไม่ import จาก CSV เก่า (สำหรับ test)
    """

    def __init__(self,
                 db_path:        Optional[str] = None,
                 skip_migration: bool = False):
        self.db_path: str = db_path or DB_FILE
        self.trades: list[TradeRecord] = []
        self.open_trades: dict = {}   # symbol → {price, amount_crypto, amount_thb}

        self._ensure_db()
        if not skip_migration:
            self._migrate_csv_if_exists()

    # ========== Schema / migration ==========

    def _ensure_db(self) -> None:
        """สร้าง directory + schema ถ้ายังไม่มี"""
        parent = os.path.dirname(self.db_path) or "."
        os.makedirs(parent, exist_ok=True)
        with sqlite3.connect(self.db_path) as con:
            con.executescript(SCHEMA)

    def _migrate_csv_if_exists(self) -> int:
        """
        ถ้ามี logs/trades.csv เก่า และ DB ยังว่าง → import เข้า SQLite
        คืนจำนวน rows ที่ import
        """
        csv_path = "logs/trades.csv"
        if not os.path.exists(csv_path):
            return 0

        with sqlite3.connect(self.db_path) as con:
            cur = con.execute("SELECT COUNT(*) FROM trades")
            if cur.fetchone()[0] > 0:
                return 0   # มีข้อมูลใน DB แล้ว — ไม่ import ซ้ำ

        rows = []
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            for r in reader:
                try:
                    rows.append((
                        r["timestamp"], r["symbol"], r["action"],
                        float(r["price"]),      float(r["amount_thb"]),
                        float(r["amount_crypto"]), float(r["fee"]),
                        float(r["pnl"]),        float(r["balance_after"]),
                    ))
                except (KeyError, ValueError) as e:
                    print(f"[PORTFOLIO] skip malformed CSV row: {e}")

        if not rows:
            return 0

        with sqlite3.connect(self.db_path) as con:
            con.executemany(
                "INSERT INTO trades (timestamp, symbol, action, price, "
                "amount_thb, amount_crypto, fee, pnl, balance_after) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        print(f"[PORTFOLIO] migrated {len(rows)} rows จาก CSV → SQLite")
        return len(rows)

    # ========== Recording ==========

    def record_buy(self, symbol: str, price: float,
                   amount_thb: float, fee: float,
                   balance_after: float) -> None:
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
        self._insert(record)
        print(f"[PORTFOLIO] BUY  {symbol} {amount_crypto:.8f} @ {price:,}")

    def record_sell(self, symbol: str, price: float,
                    amount_crypto: float, fee: float,
                    balance_after: float) -> float:
        """บันทึกการขาย + คำนวณ P&L"""
        open_trade = self.open_trades.pop(symbol, None)
        pnl = 0.0

        if open_trade:
            revenue = amount_crypto * price - fee
            cost    = open_trade["amount_thb"]
            pnl     = round(revenue - cost, 4)

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
        self._insert(record)

        sign = "+" if pnl >= 0 else "-"
        print(f"[PORTFOLIO] SELL {symbol} P&L={sign}{abs(pnl):.2f} THB")
        return pnl

    def _insert(self, r: TradeRecord) -> None:
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                "INSERT INTO trades (timestamp, symbol, action, price, "
                "amount_thb, amount_crypto, fee, pnl, balance_after) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (r.timestamp, r.symbol, r.action, r.price,
                 r.amount_thb, r.amount_crypto, r.fee, r.pnl,
                 r.balance_after),
            )

    # ========== Summary (session-scope, in-memory) ==========

    def get_summary(self) -> dict:
        """
        สรุป session ปัจจุบัน (จาก self.trades in-memory)
        — ใช้ interface เดียวกับของเดิม + เพิ่มเมตริกใหม่สำหรับ Kelly sizer
        """
        sells      = [t for t in self.trades if t.action == "sell"]
        total_pnl  = sum(t.pnl for t in sells)
        wins       = [t for t in sells if t.pnl > 0]
        losses     = [t for t in sells if t.pnl < 0]
        win_rate   = (len(wins) / len(sells) * 100) if sells else 0.0

        avg_win  = (sum(t.pnl for t in wins)   / len(wins))   if wins   else 0.0
        avg_loss = (sum(t.pnl for t in losses) / len(losses)) if losses else 0.0

        gross_profit = sum(t.pnl for t in wins)
        gross_loss   = abs(sum(t.pnl for t in losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0.0

        # expectancy = E[pnl per trade] = p*avg_win + q*avg_loss
        expectancy = 0.0
        if sells:
            p = len(wins)   / len(sells)
            q = len(losses) / len(sells)
            expectancy = p * avg_win + q * avg_loss

        return {
            "total_trades":   len(self.trades),
            "total_sells":    len(sells),
            "wins":           len(wins),
            "losses":         len(losses),
            "win_rate":       round(win_rate, 1),
            "win_rate_pct":   round(win_rate, 1),    # alias สำหรับ Kelly sizer
            "total_pnl":      round(total_pnl, 2),
            "best_trade":     max((t.pnl for t in sells), default=0),
            "worst_trade":    min((t.pnl for t in sells), default=0),
            "avg_win":        round(avg_win, 4),
            "avg_loss":       round(avg_loss, 4),
            "total_fees":     round(sum(t.fee for t in self.trades), 2),
            "profit_factor":  round(profit_factor, 3),
            "expectancy":     round(expectancy, 2),
            "open_positions": list(self.open_trades.keys()),
        }

    def print_summary(self) -> None:
        s = self.get_summary()
        print("\n" + "=" * 44)
        print(f"  รวมเทรด       : {s['total_trades']} ครั้ง")
        print(f"  Win rate      : {s['win_rate']}%  ({s['wins']}W / {s['losses']}L)")
        print(f"  P&L รวม       : {s['total_pnl']:+.2f} THB")
        print(f"  Profit factor : {s['profit_factor']:.2f}")
        print(f"  Expectancy    : {s['expectancy']:+.2f} THB/trade")
        print(f"  Avg win/loss  : +{s['avg_win']:.2f} / {s['avg_loss']:.2f}")
        print(f"  Best/Worst    : {s['best_trade']:+.2f} / {s['worst_trade']:+.2f}")
        print(f"  Total fees    : {s['total_fees']:.2f}")
        print(f"  Open positions: {s['open_positions']}")
        print("=" * 44)

    # ========== DB query helpers (all-time) ==========

    def _query(self, sql: str, params: tuple = ()) -> list[dict]:
        with sqlite3.connect(self.db_path) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_trades(self,
                   symbol:  Optional[str] = None,
                   action:  Optional[str] = None,
                   since:   Optional[str] = None,   # ISO timestamp
                   limit:   Optional[int] = None) -> list[dict]:
        """Query trades จาก DB (all-time)"""
        sql = "SELECT * FROM trades WHERE 1=1"
        params: list = []
        if symbol:
            sql += " AND symbol = ?"; params.append(symbol)
        if action:
            sql += " AND action = ?"; params.append(action)
        if since:
            sql += " AND timestamp >= ?"; params.append(since)
        sql += " ORDER BY id DESC"
        if limit:
            sql += " LIMIT ?"; params.append(limit)
        return self._query(sql, tuple(params))

    def get_pnl_by_symbol(self) -> list[dict]:
        """สรุป pnl ต่อ symbol (ทั้งหมดใน DB)"""
        sql = """
        SELECT  symbol,
                COUNT(*)                                    AS sells,
                ROUND(SUM(pnl), 2)                          AS total_pnl,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END)    AS wins,
                SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END)    AS losses,
                ROUND(AVG(CASE WHEN pnl > 0 THEN pnl END), 2) AS avg_win,
                ROUND(AVG(CASE WHEN pnl < 0 THEN pnl END), 2) AS avg_loss,
                ROUND(MAX(pnl), 2)                          AS best,
                ROUND(MIN(pnl), 2)                          AS worst
        FROM    trades
        WHERE   action = 'sell'
        GROUP BY symbol
        ORDER BY total_pnl DESC
        """
        return self._query(sql)

    def get_all_time_summary(self) -> dict:
        """
        สรุปรวมทั้งหมดใน DB (ข้าม session) — ใช้สำหรับรายงานระยะยาว
        structure เดียวกับ get_summary()
        """
        sql = """
        SELECT
          (SELECT COUNT(*) FROM trades)                                  AS total_trades,
          (SELECT COUNT(*) FROM trades WHERE action='sell')              AS total_sells,
          (SELECT COUNT(*) FROM trades WHERE action='sell' AND pnl > 0)  AS wins,
          (SELECT COUNT(*) FROM trades WHERE action='sell' AND pnl < 0)  AS losses,
          (SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE action='sell') AS total_pnl,
          (SELECT COALESCE(SUM(fee), 0) FROM trades)                     AS total_fees,
          (SELECT COALESCE(MAX(pnl), 0) FROM trades WHERE action='sell') AS best_trade,
          (SELECT COALESCE(MIN(pnl), 0) FROM trades WHERE action='sell') AS worst_trade,
          (SELECT COALESCE(AVG(pnl), 0) FROM trades WHERE action='sell' AND pnl > 0) AS avg_win,
          (SELECT COALESCE(AVG(pnl), 0) FROM trades WHERE action='sell' AND pnl < 0) AS avg_loss,
          (SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE action='sell' AND pnl > 0) AS gross_profit,
          (SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE action='sell' AND pnl < 0) AS gross_loss
        """
        row = self._query(sql)[0]
        ts  = row["total_sells"] or 0
        w   = row["wins"]   or 0
        l   = row["losses"] or 0
        win_rate = (w / ts * 100) if ts else 0.0

        gp = row["gross_profit"] or 0
        gl = abs(row["gross_loss"] or 0)
        profit_factor = (gp / gl) if gl > 0 else 0.0

        expectancy = 0.0
        if ts:
            p = w / ts
            q = l / ts
            expectancy = p * (row["avg_win"] or 0) + q * (row["avg_loss"] or 0)

        return {
            "total_trades":   row["total_trades"],
            "total_sells":    ts,
            "wins":           w,
            "losses":         l,
            "win_rate":       round(win_rate, 1),
            "win_rate_pct":   round(win_rate, 1),
            "total_pnl":      round(row["total_pnl"], 2),
            "best_trade":     row["best_trade"],
            "worst_trade":    row["worst_trade"],
            "avg_win":        round(row["avg_win"]  or 0, 4),
            "avg_loss":       round(row["avg_loss"] or 0, 4),
            "total_fees":     round(row["total_fees"], 2),
            "profit_factor":  round(profit_factor, 3),
            "expectancy":     round(expectancy, 2),
            "open_positions": list(self.open_trades.keys()),
        }

    def get_equity_curve(self,
                         symbol: Optional[str] = None,
                         since:  Optional[str] = None) -> list[dict]:
        """
        คืนลำดับจุดบน equity curve จาก DB

        แต่ละจุด:
            timestamp, balance_after, cumulative_pnl, action, symbol
        เรียงตาม id ascending (timeline)
        """
        sql = "SELECT timestamp, symbol, action, pnl, balance_after " \
              "FROM trades WHERE 1=1"
        params: list = []
        if symbol:
            sql += " AND symbol = ?"; params.append(symbol)
        if since:
            sql += " AND timestamp >= ?"; params.append(since)
        sql += " ORDER BY id ASC"

        rows = self._query(sql, tuple(params))
        cum = 0.0
        curve = []
        for r in rows:
            cum += r["pnl"] or 0.0
            curve.append({
                "timestamp":      r["timestamp"],
                "symbol":         r["symbol"],
                "action":         r["action"],
                "balance_after":  r["balance_after"],
                "cumulative_pnl": round(cum, 2),
            })
        return curve

    def load_from_db(self) -> int:
        """โหลด trades ทั้งหมดจาก DB เข้า self.trades (restore state)"""
        self.trades = []
        rows = self._query("SELECT * FROM trades ORDER BY id ASC")
        for r in rows:
            self.trades.append(TradeRecord(
                timestamp     = r["timestamp"],
                symbol        = r["symbol"],
                action        = r["action"],
                price         = r["price"],
                amount_thb    = r["amount_thb"],
                amount_crypto = r["amount_crypto"],
                fee           = r["fee"],
                pnl           = r["pnl"],
                balance_after = r["balance_after"],
            ))
        return len(self.trades)

    def export_csv(self, path: str = "logs/trades_export.csv") -> int:
        """Export trades ทั้งหมดกลับไปเป็น CSV (backward-compat + portability)"""
        rows = self.get_trades()
        if not rows:
            return 0
        parent = os.path.dirname(path) or "."
        os.makedirs(parent, exist_ok=True)
        # exclude sqlite 'id' column, match original CSV schema
        fields = ["timestamp", "symbol", "action", "price",
                  "amount_thb", "amount_crypto", "fee", "pnl",
                  "balance_after"]
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in rows:
                w.writerow({k: r[k] for k in fields})
        return len(rows)

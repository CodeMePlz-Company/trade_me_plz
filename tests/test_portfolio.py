"""
Tests for execution/portfolio.py (SQLite-backed)

ครอบคลุม:
- Schema + DB creation
- record_buy          — เก็บ open_trade + trades + row ใน DB
- record_sell         — คำนวณ P&L ถูก (กำไร / ขาดทุน / ไม่มี open)
- Persistence         — DB เก็บรายการแบบ persistent
- get_summary         — สถิติ session-scope (win rate, total P&L, best/worst)
- get_all_time_summary — สถิติ all-time จาก DB
- get_trades / get_pnl_by_symbol — query helpers
- load_from_db / export_csv — restore + export
- CSV migration       — one-shot import จาก logs/trades.csv เก่า
- skip_migration      — bypass CSV import
- ไม่มีเทรด           — summary ไม่พัง

ใช้ tmp_path + monkeypatch.chdir เพื่อไม่แตะไฟล์ logs/ ของจริง
"""
import csv
import sqlite3
import pytest
from execution.portfolio import Portfolio, DB_FILE, LOG_FILE


@pytest.fixture
def portfolio(tmp_path, monkeypatch):
    """สร้าง Portfolio ใหม่ใน tmp directory เพื่อกันไฟล์ shared state"""
    monkeypatch.chdir(tmp_path)
    return Portfolio()


# ========== Initialization ==========

class TestInit:
    def test_creates_db_file(self, portfolio, tmp_path):
        db_path = tmp_path / DB_FILE
        assert db_path.exists()

    def test_log_file_alias_points_to_db(self):
        assert LOG_FILE == DB_FILE

    def test_schema_has_expected_columns(self, portfolio, tmp_path):
        with sqlite3.connect(tmp_path / DB_FILE) as con:
            cols = [r[1] for r in con.execute("PRAGMA table_info(trades)")]
        for c in ["id", "timestamp", "symbol", "action", "price",
                  "amount_thb", "amount_crypto", "fee", "pnl",
                  "balance_after"]:
            assert c in cols

    def test_trades_list_starts_empty(self, portfolio):
        assert portfolio.trades == []
        assert portfolio.open_trades == {}

    def test_custom_db_path(self, tmp_path):
        custom = tmp_path / "custom/t.db"
        p = Portfolio(db_path=str(custom), skip_migration=True)
        assert custom.exists()
        assert p.db_path == str(custom)


# ========== record_buy ==========

class TestRecordBuy:
    def test_adds_to_open_trades(self, portfolio):
        portfolio.record_buy("BTC_THB",
            price=1_000_000, amount_thb=1000,
            fee=2.5, balance_after=9000)

        assert "BTC_THB" in portfolio.open_trades
        assert portfolio.open_trades["BTC_THB"]["price"] == 1_000_000

    def test_calculates_crypto_amount_after_fee(self, portfolio):
        portfolio.record_buy("BTC_THB",
            price=1_000_000, amount_thb=1000,
            fee=2.5, balance_after=9000)

        expected_crypto = (1000 - 2.5) / 1_000_000
        assert portfolio.open_trades["BTC_THB"]["amount_crypto"] == expected_crypto

    def test_appends_to_trades_list(self, portfolio):
        portfolio.record_buy("BTC_THB", 1_000_000, 1000, 2.5, 9000)
        assert len(portfolio.trades) == 1
        assert portfolio.trades[0].action == "buy"
        assert portfolio.trades[0].pnl == 0.0

    def test_writes_row_to_db(self, portfolio, tmp_path):
        portfolio.record_buy("BTC_THB", 1_000_000, 1000, 2.5, 9000)
        with sqlite3.connect(tmp_path / DB_FILE) as con:
            cnt = con.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        assert cnt == 1

    def test_zero_price_does_not_crash(self, portfolio):
        """edge case: price=0 ไม่ควร div-by-zero"""
        portfolio.record_buy("BTC_THB",
            price=0, amount_thb=1000, fee=2.5, balance_after=9000)
        assert portfolio.open_trades["BTC_THB"]["amount_crypto"] == 0


# ========== record_sell ==========

class TestRecordSell:
    def test_profitable_sell_has_positive_pnl(self, portfolio):
        # ซื้อที่ 1,000,000 ใช้ 1000 THB, fee 2.5 → ได้ crypto 0.0009975
        portfolio.record_buy("BTC_THB", 1_000_000, 1000, 2.5, 9000)

        # ขายที่ 1,100,000 (ขึ้น 10%)
        crypto = portfolio.open_trades["BTC_THB"]["amount_crypto"]
        pnl = portfolio.record_sell("BTC_THB",
            price=1_100_000, amount_crypto=crypto,
            fee=2.75, balance_after=10_000)

        # revenue = 0.0009975 * 1_100_000 - 2.75 = 1097.25 - 2.75 = 1094.5
        # cost    = 1000
        # pnl     = 94.5
        assert pnl > 0
        assert pnl == pytest.approx(94.5, abs=0.1)

    def test_losing_sell_has_negative_pnl(self, portfolio):
        portfolio.record_buy("BTC_THB", 1_000_000, 1000, 2.5, 9000)

        crypto = portfolio.open_trades["BTC_THB"]["amount_crypto"]
        pnl = portfolio.record_sell("BTC_THB",
            price=900_000, amount_crypto=crypto,
            fee=2.25, balance_after=8_000)

        assert pnl < 0

    def test_sell_removes_from_open_trades(self, portfolio):
        portfolio.record_buy("BTC_THB", 1_000_000, 1000, 2.5, 9000)
        crypto = portfolio.open_trades["BTC_THB"]["amount_crypto"]

        portfolio.record_sell("BTC_THB", 1_100_000, crypto, 2.75, 10000)
        assert "BTC_THB" not in portfolio.open_trades

    def test_sell_without_open_trade_gives_zero_pnl(self, portfolio):
        """ขายโดยไม่มี open trade → P&L = 0 (ไม่มีข้อมูลต้นทุน)"""
        pnl = portfolio.record_sell("BTC_THB",
            price=1_100_000, amount_crypto=0.001,
            fee=2.75, balance_after=10_000)
        assert pnl == 0.0

    def test_sell_writes_row_to_db(self, portfolio, tmp_path):
        portfolio.record_buy("BTC_THB", 1_000_000, 1000, 2.5, 9000)
        c = portfolio.open_trades["BTC_THB"]["amount_crypto"]
        portfolio.record_sell("BTC_THB", 1_100_000, c, 2.75, 10000)
        with sqlite3.connect(tmp_path / DB_FILE) as con:
            cnt = con.execute(
                "SELECT COUNT(*) FROM trades WHERE action='sell'").fetchone()[0]
        assert cnt == 1


# ========== SQLite persistence ==========

class TestPersistence:
    def test_row_has_correct_data(self, portfolio, tmp_path):
        portfolio.record_buy("BTC_THB", 1_000_000, 1000, 2.5, 9000)

        with sqlite3.connect(tmp_path / DB_FILE) as con:
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT * FROM trades").fetchone()

        assert row["symbol"] == "BTC_THB"
        assert row["action"] == "buy"
        assert row["price"]  == 1_000_000

    def test_multiple_rows_persist(self, portfolio, tmp_path):
        portfolio.record_buy("BTC_THB", 1_000_000, 1000, 2.5, 9000)
        c = portfolio.open_trades["BTC_THB"]["amount_crypto"]
        portfolio.record_sell("BTC_THB", 1_100_000, c, 2.75, 10000)

        with sqlite3.connect(tmp_path / DB_FILE) as con:
            rows = con.execute(
                "SELECT action FROM trades ORDER BY id").fetchall()
        assert [r[0] for r in rows] == ["buy", "sell"]

    def test_check_constraint_blocks_bad_action(self, portfolio, tmp_path):
        with sqlite3.connect(tmp_path / DB_FILE) as con:
            with pytest.raises(sqlite3.IntegrityError):
                con.execute(
                    "INSERT INTO trades (timestamp, symbol, action, price, "
                    "amount_thb, amount_crypto) VALUES "
                    "('2025-01-01', 'X', 'dance', 1, 1, 1)")


# ========== get_summary (session-scope) ==========

class TestGetSummary:
    def test_empty_portfolio_gives_zero_stats(self, portfolio):
        s = portfolio.get_summary()
        assert s["total_trades"] == 0
        assert s["total_sells"] == 0
        assert s["win_rate"] == 0
        assert s["total_pnl"] == 0
        assert s["best_trade"] == 0
        assert s["worst_trade"] == 0

    def test_counts_wins_and_losses_correctly(self, portfolio):
        # กำไร
        portfolio.record_buy("BTC_THB", 1_000_000, 1000, 2.5, 9000)
        c1 = portfolio.open_trades["BTC_THB"]["amount_crypto"]
        portfolio.record_sell("BTC_THB", 1_100_000, c1, 2.75, 10000)

        # ขาดทุน
        portfolio.record_buy("ETH_THB", 50_000, 1000, 2.5, 9000)
        c2 = portfolio.open_trades["ETH_THB"]["amount_crypto"]
        portfolio.record_sell("ETH_THB", 45_000, c2, 2.25, 8000)

        s = portfolio.get_summary()
        assert s["total_sells"] == 2
        assert s["wins"] == 1
        assert s["losses"] == 1
        assert s["win_rate"] == 50.0

    def test_summary_tracks_best_and_worst(self, portfolio):
        portfolio.record_buy("BTC_THB", 1_000_000, 1000, 2.5, 9000)
        c1 = portfolio.open_trades["BTC_THB"]["amount_crypto"]
        portfolio.record_sell("BTC_THB", 1_200_000, c1, 3.0, 10000)

        portfolio.record_buy("ETH_THB", 50_000, 1000, 2.5, 9000)
        c2 = portfolio.open_trades["ETH_THB"]["amount_crypto"]
        portfolio.record_sell("ETH_THB", 40_000, c2, 2.0, 8000)

        s = portfolio.get_summary()
        assert s["best_trade"] > 0
        assert s["worst_trade"] < 0
        assert s["best_trade"] > s["worst_trade"]

    def test_open_positions_reported_in_summary(self, portfolio):
        portfolio.record_buy("BTC_THB", 1_000_000, 1000, 2.5, 9000)
        portfolio.record_buy("ETH_THB", 50_000, 1000, 2.5, 8000)

        s = portfolio.get_summary()
        assert set(s["open_positions"]) == {"BTC_THB", "ETH_THB"}

    def test_enhanced_stats_present(self, portfolio):
        portfolio.record_buy("BTC_THB", 1_000_000, 1000, 2.5, 9000)
        c1 = portfolio.open_trades["BTC_THB"]["amount_crypto"]
        portfolio.record_sell("BTC_THB", 1_100_000, c1, 2.75, 10000)
        portfolio.record_buy("ETH_THB", 50_000, 1000, 2.5, 9000)
        c2 = portfolio.open_trades["ETH_THB"]["amount_crypto"]
        portfolio.record_sell("ETH_THB", 45_000, c2, 2.25, 8000)

        s = portfolio.get_summary()
        for k in ("avg_win", "avg_loss", "profit_factor",
                  "expectancy", "total_fees", "win_rate_pct"):
            assert k in s
        assert s["avg_win"]  > 0
        assert s["avg_loss"] < 0
        assert s["profit_factor"] > 0
        assert s["win_rate_pct"] == s["win_rate"]


# ========== DB query helpers ==========

class TestQueries:
    def _make(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        p = Portfolio()
        p.record_buy("BTC_THB", 1_000_000, 1000, 2.5, 9000)
        c = p.open_trades["BTC_THB"]["amount_crypto"]
        p.record_sell("BTC_THB", 1_100_000, c, 2.75, 10000)
        p.record_buy("ETH_THB", 50_000, 1000, 2.5, 9000)
        c2 = p.open_trades["ETH_THB"]["amount_crypto"]
        p.record_sell("ETH_THB", 45_000, c2, 2.25, 8000)
        return p

    def test_get_trades_all(self, tmp_path, monkeypatch):
        p = self._make(tmp_path, monkeypatch)
        assert len(p.get_trades()) == 4

    def test_get_trades_by_symbol(self, tmp_path, monkeypatch):
        p = self._make(tmp_path, monkeypatch)
        assert len(p.get_trades(symbol="BTC_THB")) == 2
        assert len(p.get_trades(symbol="XRP_THB")) == 0

    def test_get_trades_by_action(self, tmp_path, monkeypatch):
        p = self._make(tmp_path, monkeypatch)
        assert len(p.get_trades(action="buy"))  == 2
        assert len(p.get_trades(action="sell")) == 2

    def test_get_trades_with_limit(self, tmp_path, monkeypatch):
        p = self._make(tmp_path, monkeypatch)
        assert len(p.get_trades(limit=2)) == 2

    def test_get_pnl_by_symbol(self, tmp_path, monkeypatch):
        p = self._make(tmp_path, monkeypatch)
        rows = p.get_pnl_by_symbol()
        assert len(rows) == 2
        symbols = {r["symbol"] for r in rows}
        assert symbols == {"BTC_THB", "ETH_THB"}
        btc = next(r for r in rows if r["symbol"] == "BTC_THB")
        assert btc["total_pnl"] > 0
        assert btc["sells"] == 1

    def test_all_time_summary(self, tmp_path, monkeypatch):
        p = self._make(tmp_path, monkeypatch)
        s = p.get_all_time_summary()
        assert s["total_trades"] == 4
        assert s["total_sells"]  == 2
        assert s["wins"]   == 1
        assert s["losses"] == 1
        assert s["win_rate"] == 50.0
        assert "profit_factor" in s


# ========== load_from_db / export_csv ==========

class TestLoadAndExport:
    def test_load_restores_session_state(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        p = Portfolio()
        p.record_buy("BTC_THB", 1_000_000, 1000, 2.5, 9000)
        c = p.open_trades["BTC_THB"]["amount_crypto"]
        p.record_sell("BTC_THB", 1_100_000, c, 2.75, 10000)

        # ใหม่ → trades ว่าง, DB ยัง persist
        p2 = Portfolio(skip_migration=True)
        assert p2.trades == []

        n = p2.load_from_db()
        assert n == 2
        assert len(p2.trades) == 2
        assert any(t.pnl != 0 for t in p2.trades)

    def test_export_csv_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        p = Portfolio()
        p.record_buy("BTC_THB", 1_000_000, 1000, 2.5, 9000)
        c = p.open_trades["BTC_THB"]["amount_crypto"]
        p.record_sell("BTC_THB", 1_100_000, c, 2.75, 10000)

        n = p.export_csv("logs/out.csv")
        assert n == 2
        assert (tmp_path / "logs/out.csv").exists()

        with open(tmp_path / "logs/out.csv") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 2
        assert set(rows[0]) == {
            "timestamp", "symbol", "action", "price",
            "amount_thb", "amount_crypto", "fee", "pnl",
            "balance_after",
        }


# ========== CSV migration ==========

class TestCSVMigration:
    def _write_legacy(self, tmp_path):
        (tmp_path / "logs").mkdir(exist_ok=True)
        with open(tmp_path / "logs/trades.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "timestamp", "symbol", "action", "price",
                "amount_thb", "amount_crypto", "fee",
                "pnl", "balance_after",
            ])
            w.writerow([
                "2025-01-01T00:00:00", "BTC_THB", "buy",
                "1000000", "1000", "0.000997", "2.5", "0", "9000",
            ])
            w.writerow([
                "2025-01-02T00:00:00", "BTC_THB", "sell",
                "1100000", "1100", "0.000997", "2.75", "94.5", "10000",
            ])

    def test_auto_migrates_legacy_csv(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        self._write_legacy(tmp_path)
        p = Portfolio()
        s = p.get_all_time_summary()
        assert s["total_trades"] == 2
        assert s["total_sells"] == 1
        assert s["total_pnl"] == pytest.approx(94.5, abs=0.1)

    def test_no_duplicate_migration(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        self._write_legacy(tmp_path)
        Portfolio()   # first — migrates
        p2 = Portfolio()  # second — should NOT re-import
        assert p2.get_all_time_summary()["total_trades"] == 2

    def test_skip_migration_flag(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        self._write_legacy(tmp_path)
        p = Portfolio(skip_migration=True)
        assert p.get_all_time_summary()["total_trades"] == 0

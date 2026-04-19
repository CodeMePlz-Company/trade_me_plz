"""
Tests for execution/portfolio.py

ครอบคลุม:
- record_buy          — เก็บ open_trade + trades ถูก
- record_sell         — คำนวณ P&L ถูก (กำไร / ขาดทุน / ไม่มี open)
- CSV logging         — เขียนไฟล์ header + records
- get_summary         — สถิติ (win rate, total P&L, best/worst)
- ไม่มีเทรด           — summary ไม่พัง

ใช้ tmp_path + monkeypatch.chdir เพื่อไม่แตะไฟล์ logs/ ของจริง
"""
import csv
import pytest
from execution.portfolio import Portfolio, LOG_FILE


@pytest.fixture
def portfolio(tmp_path, monkeypatch):
    """สร้าง Portfolio ใหม่ใน tmp directory เพื่อกันไฟล์ shared state"""
    monkeypatch.chdir(tmp_path)
    return Portfolio()


# ========== Initialization ==========

class TestInit:
    def test_creates_log_file_with_header(self, portfolio, tmp_path):
        log_path = tmp_path / LOG_FILE
        assert log_path.exists()

        with open(log_path) as f:
            header = f.readline().strip().split(",")
        expected = ["timestamp", "symbol", "action", "price",
                    "amount_thb", "amount_crypto", "fee",
                    "pnl", "balance_after"]
        assert header == expected

    def test_trades_list_starts_empty(self, portfolio):
        assert portfolio.trades == []
        assert portfolio.open_trades == {}


# ========== record_buy ==========

class TestRecordBuy:
    def test_adds_to_open_trades(self, portfolio):
        portfolio.record_buy("BTC_THB",
            price=1_000_000, amount_thb=1000,
            fee=2.5, balance_after=9000)

        assert "BTC_THB" in portfolio.open_trades
        assert portfolio.open_trades["BTC_THB"]["price"] == 1_000_000

    def test_calculates_crypto_amount_after_fee(self, portfolio):
        # amount_thb=1000, fee=2.5 → (1000-2.5)/1_000_000 crypto
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
        # ขายที่ 900,000 (ลง 10%)
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


# ========== CSV Logging ==========

class TestCSVLogging:
    def test_buy_record_written_to_csv(self, portfolio, tmp_path):
        portfolio.record_buy("BTC_THB", 1_000_000, 1000, 2.5, 9000)

        with open(tmp_path / LOG_FILE) as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == 1
        assert rows[0]["symbol"] == "BTC_THB"
        assert rows[0]["action"] == "buy"
        assert float(rows[0]["price"]) == 1_000_000

    def test_multiple_records_appended(self, portfolio, tmp_path):
        portfolio.record_buy("BTC_THB", 1_000_000, 1000, 2.5, 9000)
        crypto = portfolio.open_trades["BTC_THB"]["amount_crypto"]
        portfolio.record_sell("BTC_THB", 1_100_000, crypto, 2.75, 10000)

        with open(tmp_path / LOG_FILE) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 2
        assert rows[0]["action"] == "buy"
        assert rows[1]["action"] == "sell"


# ========== get_summary ==========

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
        # เทรดที่กำไร
        portfolio.record_buy("BTC_THB", 1_000_000, 1000, 2.5, 9000)
        c1 = portfolio.open_trades["BTC_THB"]["amount_crypto"]
        portfolio.record_sell("BTC_THB", 1_100_000, c1, 2.75, 10000)

        # เทรดที่ขาดทุน
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
        portfolio.record_sell("BTC_THB", 1_200_000, c1, 3.0, 10000)  # กำไรมาก

        portfolio.record_buy("ETH_THB", 50_000, 1000, 2.5, 9000)
        c2 = portfolio.open_trades["ETH_THB"]["amount_crypto"]
        portfolio.record_sell("ETH_THB", 40_000, c2, 2.0, 8000)      # ขาดทุนมาก

        s = portfolio.get_summary()
        assert s["best_trade"] > 0
        assert s["worst_trade"] < 0
        assert s["best_trade"] > s["worst_trade"]

    def test_open_positions_reported_in_summary(self, portfolio):
        portfolio.record_buy("BTC_THB", 1_000_000, 1000, 2.5, 9000)
        portfolio.record_buy("ETH_THB", 50_000, 1000, 2.5, 8000)

        s = portfolio.get_summary()
        assert set(s["open_positions"]) == {"BTC_THB", "ETH_THB"}

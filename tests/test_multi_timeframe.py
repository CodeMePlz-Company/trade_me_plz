"""
tests/test_multi_timeframe.py — tests สำหรับ brain.multi_timeframe
ทดสอบทั้ง strict + lenient modes ด้วย mock indicator_fn
"""
import pytest

from brain.multi_timeframe import confirm, MTFDecision


def _mk_indicators(consensus: str, buy_count=0, sell_count=0, adx=30):
    """helper สร้าง mock result ของ get_all_indicators"""
    return {
        "consensus":  consensus,
        "buy_count":  buy_count,
        "sell_count": sell_count,
        "adx":        {"adx": adx, "plus_di": 25, "minus_di": 15},
    }


class TestHoldAction:
    def test_hold_always_allows(self):
        dec = confirm("BTC_THB", "hold",
                      _indicator_fn=lambda s, resolution: {})
        assert dec.allow is True
        assert dec.confidence_delta == 0.0


class TestMissingData:
    def test_strict_rejects_missing(self):
        dec = confirm("BTC_THB", "buy", mode="strict",
                      _indicator_fn=lambda s, resolution: {})
        assert dec.allow is False
        assert dec.confidence_delta < 0

    def test_lenient_allows_missing(self):
        dec = confirm("BTC_THB", "buy", mode="lenient",
                      _indicator_fn=lambda s, resolution: {})
        assert dec.allow is True
        assert dec.confidence_delta == 0.0


class TestAgree:
    def test_buy_confirmed_by_htf_buy(self):
        dec = confirm("BTC_THB", "buy",
                      _indicator_fn=lambda s, resolution: _mk_indicators("buy", 5))
        assert dec.allow is True
        assert dec.confidence_delta > 0
        assert "confirms" in dec.reason

    def test_sell_confirmed_by_htf_sell(self):
        dec = confirm("BTC_THB", "sell",
                      _indicator_fn=lambda s, resolution: _mk_indicators("sell", 0, 5))
        assert dec.allow is True
        assert dec.confidence_delta > 0


class TestOppose:
    def test_buy_blocked_by_htf_sell_lenient(self):
        dec = confirm("BTC_THB", "buy", mode="lenient",
                      _indicator_fn=lambda s, resolution: _mk_indicators("sell", 0, 5))
        assert dec.allow is False
        assert dec.confidence_delta < 0
        assert "opposes" in dec.reason

    def test_buy_blocked_by_htf_sell_strict(self):
        dec = confirm("BTC_THB", "buy", mode="strict",
                      _indicator_fn=lambda s, resolution: _mk_indicators("sell", 0, 5))
        assert dec.allow is False

    def test_sell_blocked_by_htf_buy(self):
        dec = confirm("BTC_THB", "sell",
                      _indicator_fn=lambda s, resolution: _mk_indicators("buy", 5))
        assert dec.allow is False


class TestNeutral:
    def test_neutral_htf_strict_blocks(self):
        dec = confirm("BTC_THB", "buy", mode="strict",
                      _indicator_fn=lambda s, resolution: _mk_indicators("neutral", 2, 2))
        assert dec.allow is False
        assert dec.confidence_delta < 0

    def test_neutral_htf_lenient_passes(self):
        dec = confirm("BTC_THB", "buy", mode="lenient",
                      _indicator_fn=lambda s, resolution: _mk_indicators("neutral", 2, 2))
        assert dec.allow is True
        assert dec.confidence_delta == 0.0


class TestDeltaMagnitude:
    def test_boost_value_used(self):
        dec = confirm("BTC_THB", "buy", boost=0.25,
                      _indicator_fn=lambda s, resolution: _mk_indicators("buy", 5))
        assert dec.confidence_delta == 0.25

    def test_penalty_value_used(self):
        dec = confirm("BTC_THB", "buy", penalty=0.40,
                      _indicator_fn=lambda s, resolution: _mk_indicators("sell", 0, 5))
        assert dec.confidence_delta == -0.40


class TestHTFResolution:
    def test_higher_resolution_passed_through(self):
        captured = {}
        def spy(symbol, resolution):
            captured["res"] = resolution
            return _mk_indicators("buy", 5)

        confirm("BTC_THB", "buy", higher_resolution="1D",
                _indicator_fn=spy)
        assert captured["res"] == "1D"

    def test_decision_includes_htf_fields(self):
        dec = confirm("BTC_THB", "buy", higher_resolution="240",
                      _indicator_fn=lambda s, resolution:
                      _mk_indicators("buy", 5, adx=42))
        assert dec.higher_tf == "240"
        assert dec.higher_consensus == "buy"
        assert dec.higher_adx == 42

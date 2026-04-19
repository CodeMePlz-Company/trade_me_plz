"""
metrics.py — คำนวณสถิติประสิทธิภาพจาก backtest result

Metrics:
    total_return_pct   — % ผลตอบแทนรวม
    cagr_pct           — Compound Annual Growth Rate (annualized)
    max_drawdown_pct   — ขาดทุนสูงสุดจากยอด peak
    sharpe             — (return_mean - rf) / return_std * √annualization
    sortino            — Sharpe แต่ใช้ downside deviation
    win_rate_pct       — % trade ที่กำไร
    profit_factor      — gross_profit / gross_loss
    avg_win / avg_loss — ค่าเฉลี่ยกำไร/ขาดทุนต่อ trade
    expectancy         — ค่าคาดหวังต่อ trade
    total_trades
    total_fees
"""
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backtest.engine import BacktestResult


def _returns_series(equity_curve: list[tuple[int, float]]) -> list[float]:
    """คำนวณ % returns ของแต่ละ bar"""
    rets = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1][1]
        cur  = equity_curve[i][1]
        if prev > 0:
            rets.append(cur / prev - 1)
    return rets


def _max_drawdown(equity_curve: list[tuple[int, float]]) -> float:
    """% drawdown สูงสุด (เป็นจำนวนลบ)"""
    if not equity_curve:
        return 0.0

    peak = equity_curve[0][1]
    max_dd = 0.0

    for _, eq in equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            dd = (eq - peak) / peak
            max_dd = min(max_dd, dd)

    return max_dd * 100


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _sharpe(returns: list[float], bars_per_year: int = 24 * 365) -> float:
    """
    Sharpe ratio annualized
    bars_per_year: default = 1H bars (24 × 365 = 8760)
    สำหรับ 1D ให้ส่ง 365; 4H ให้ 6 × 365 = 2190
    """
    if not returns:
        return 0.0
    mean = _mean(returns)
    std  = _std(returns)
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(bars_per_year)


def _sortino(returns: list[float], bars_per_year: int = 24 * 365) -> float:
    if not returns:
        return 0.0
    negatives = [r for r in returns if r < 0]
    if not negatives:
        return float("inf")
    mean = _mean(returns)
    dd   = math.sqrt(sum(r * r for r in negatives) / len(negatives))
    if dd == 0:
        return 0.0
    return (mean / dd) * math.sqrt(bars_per_year)


def _cagr(equity_curve: list[tuple[int, float]]) -> float:
    """Compound Annual Growth Rate (%)"""
    if len(equity_curve) < 2:
        return 0.0
    start_ts, start_eq = equity_curve[0]
    end_ts,   end_eq   = equity_curve[-1]
    years = (end_ts - start_ts) / (365 * 86400)
    if years <= 0 or start_eq <= 0:
        return 0.0
    return ((end_eq / start_eq) ** (1 / years) - 1) * 100


def compute_metrics(result, bars_per_year: int = 24 * 365) -> dict:
    """
    คำนวณ metrics ทั้งหมดจาก BacktestResult

    bars_per_year: ใช้สำหรับ annualize Sharpe/Sortino
        - 1H  → 24 × 365 = 8760
        - 4H  → 6  × 365 = 2190
        - 1D  → 365
    """
    trades = result.trades
    sells  = [t for t in trades if t.action == "sell"]

    wins    = [t for t in sells if t.pnl > 0]
    losses  = [t for t in sells if t.pnl < 0]

    gross_profit = sum(t.pnl for t in wins)
    gross_loss   = abs(sum(t.pnl for t in losses))

    avg_win  = _mean([t.pnl for t in wins])      if wins   else 0.0
    avg_loss = _mean([t.pnl for t in losses])    if losses else 0.0

    win_rate = len(wins) / len(sells) * 100 if sells else 0.0

    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    expectancy = ((win_rate / 100) * avg_win
                  + (1 - win_rate / 100) * avg_loss) if sells else 0.0

    total_fees = sum(t.fee for t in trades)

    total_return_pct = ((result.end_equity - result.start_cash)
                        / result.start_cash * 100)

    returns = _returns_series(result.equity_curve)

    return {
        "symbol":             result.symbol,
        "start_cash":         result.start_cash,
        "end_equity":         round(result.end_equity, 2),
        "total_return_pct":   round(total_return_pct, 2),
        "cagr_pct":           round(_cagr(result.equity_curve), 2),
        "max_drawdown_pct":   round(_max_drawdown(result.equity_curve), 2),
        "sharpe":             round(_sharpe(returns, bars_per_year), 2),
        "sortino":            round(_sortino(returns, bars_per_year), 2),
        "total_trades":       len(trades),
        "total_sells":        len(sells),
        "wins":               len(wins),
        "losses":             len(losses),
        "win_rate_pct":       round(win_rate, 1),
        "profit_factor":      round(profit_factor, 2) if profit_factor != float("inf") else "∞",
        "avg_win":            round(avg_win, 2),
        "avg_loss":           round(avg_loss, 2),
        "expectancy":         round(expectancy, 2),
        "total_fees":         round(total_fees, 2),
        "stop_loss_hits":     result.stop_loss_hits,
        "take_profit_hits":   result.take_profit_hits,
        "trailing_stop_hits": result.trailing_stop_hits,
        "best_trade":         round(max((t.pnl for t in sells), default=0), 2),
        "worst_trade":        round(min((t.pnl for t in sells), default=0), 2),
    }

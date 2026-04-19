"""
backtest/ — Backtesting engine สำหรับ Trade Me Plz

วัตถุประสงค์: ย้อนทดสอบกลยุทธ์บนข้อมูล OHLCV จริง (หรือ synthetic)
ก่อนเปิด SIMULATION_MODE=False

Modules:
    data_loader  — ดึง/cache ข้อมูลย้อนหลัง + สร้าง synthetic data
    engine       — BacktestEngine หลัก + SimPortfolio
    metrics      — คำนวณ Sharpe, max drawdown, win rate, etc.
    report       — สร้างรายงาน text + HTML
    run          — CLI entry point
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ========== API ==========
API_KEY    = os.getenv("API_KEY", "")
API_SECRET = os.getenv("API_SECRET", "")

# ========== Webhook ==========
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "mysecret123")
WEBHOOK_PORT   = int(os.getenv("WEBHOOK_PORT", 5000))

# ========== LINE ==========
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_TARGET_ID            = os.getenv("LINE_TARGET_ID", "")

# ========== Trading ==========
SYMBOLS    = ["BTC_THB", "ETH_THB", "XRP_THB"]  # coin ที่ต้องการเทรด
RESOLUTION = "60"                                 # timeframe หลัก: 1, 5, 15, 60, 240

# ========== Multi-Timeframe ==========
# ใช้ timeframe ใหญ่กว่า confirm ก่อนเข้า entry (เช่น เข้า 1H ต้องให้ 4H agree)
MTF_ENABLED            = True
MTF_HIGHER_RESOLUTION  = "240"      # 4H confirm trade 1H
# strict = ต้อง agree ทิศเดียวกัน / lenient = ห้าม oppose (neutral ผ่าน)
MTF_MODE               = "lenient"  # "strict" | "lenient"
MTF_CONFIDENCE_BOOST   = 0.15       # HTF agree → +0.15 confidence
MTF_CONFIDENCE_PENALTY = 0.30       # (strict) HTF neutral → −0.30 confidence

# ========== Strategy ==========
STRATEGY_MODE   = "combined"   # indicator / spread / combined
MIN_CONFIDENCE  = 0.50         # confidence ขั้นต่ำ
MIN_SPREAD_PCT  = 0.30         # spread ขั้นต่ำสำหรับ arbitrage

# ========== Risk ==========
MAX_POSITION_PCT  = 0.10   # ใช้เงินไม่เกิน 10% ต่อ order (เพดาน — ทุกโหมดต้องไม่เกินนี้)
MIN_POSITION_THB  = 20.0   # ขั้นต่ำที่ Bitkub รับ
MAX_DAILY_LOSS    = 0.05   # หยุดเทรดถ้าขาดทุนเกิน 5% ต่อวัน
STOP_LOSS_PCT     = 0.03   # hard stop-loss 3%
TAKE_PROFIT_PCT   = 0.05   # take-profit 5%
TRAILING_STOP_PCT = 0.02   # trailing stop 2% จาก peak (0 = ปิดใช้งาน)

# ========== Position Sizing ==========
# โหมด: "fixed" / "kelly" / "atr" / "hybrid"
POSITION_SIZING_MODE   = "fixed"

# Kelly Criterion params (ใช้เมื่อ mode = kelly/hybrid)
KELLY_FRACTION         = 0.25   # ใช้ 1/4 Kelly — conservative
KELLY_MIN_TRADES       = 20     # ต้องมีประวัติ ≥ N trades ก่อนใช้ Kelly

# ATR-based params (ใช้เมื่อ mode = atr/hybrid)
ATR_RISK_PER_TRADE_PCT = 0.01   # เสี่ยง 1% ของ balance ต่อ trade
ATR_STOP_MULTIPLIER    = 2.0    # stop-loss = entry − 2×ATR

# ========== Loop ==========
SCAN_INTERVAL_SEC   = 60    # สแกนทุก 60 วินาที
STOP_LOSS_CHECK_SEC = 10    # เช็ค stop-loss ทุก 10 วินาที
SUMMARY_HOUR        = 22    # ส่งสรุปตอน 22:00

# ========== Simulation ==========
SIMULATION_MODE = True   # True = ไม่ส่ง order จริง, False = เทรดจริง
from flask import Flask, request, jsonify
import json
import os
from datetime import datetime

app = Flask(__name__)

# เก็บ signals ที่รับมา (ในการใช้จริงควรใส่ใน queue หรือ DB)
signal_queue = []

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "mysecret123")

@app.route("/webhook", methods=["POST"])
def receive_signal():
    """
    รับ signal จาก TradingView
    ตั้ง Alert บน TradingView แล้วใส่ URL นี้ + JSON body
    """
    # ตรวจ secret key
    secret = request.args.get("secret", "")
    if secret != WEBHOOK_SECRET:
        return jsonify({"error": "unauthorized"}), 401

    try:
        data = request.get_json()

        # TradingView ส่ง body มาแบบนี้ (ออกแบบเองได้ใน Alert message)
        # {
        #   "action": "buy",          ← buy / sell / close
        #   "symbol": "BTCTHB",
        #   "price": {{close}},       ← TradingView variable
        #   "timeframe": "1h",
        #   "strategy": "RSI_Cross"
        # }

        signal = {
            "action":    data.get("action"),      # buy / sell / close
            "symbol":    data.get("symbol"),
            "price":     data.get("price"),
            "timeframe": data.get("timeframe"),
            "strategy":  data.get("strategy"),
            "received":  datetime.now().isoformat(),
        }

        print(f"[WEBHOOK] signal received: {signal}")
        signal_queue.append(signal)

        return jsonify({"status": "ok", "signal": signal})

    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/signals", methods=["GET"])
def get_signals():
    """ดู signals ที่รับมาแล้ว"""
    return jsonify(signal_queue[-20:])  # 20 อันล่าสุด

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "running", "signals": len(signal_queue)})

if __name__ == "__main__":
    # รัน server บน port 5000
    # ใช้ ngrok เพื่อเปิด public URL ให้ TradingView ส่งมาได้
    app.run(host="0.0.0.0", port=5000, debug=False)
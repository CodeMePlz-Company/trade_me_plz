"""
run_dashboard.py — entry-point สำหรับรัน web dashboard แบบ standalone

Usage:
    python run_dashboard.py
    DASHBOARD_PORT=9000 python run_dashboard.py

หรือรันด้วย uvicorn ตรงๆ:
    uvicorn dashboard.server:app --reload
"""
from dashboard.server import main

if __name__ == "__main__":
    main()

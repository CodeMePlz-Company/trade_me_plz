"""
conftest.py — pytest configuration
เพิ่ม project root ลงใน sys.path เพื่อให้ import execution / brain ได้จาก tests/
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

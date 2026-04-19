# Trade Me Plz 📈

Welcome to **Trade Me Plz**, a professional-grade trading and investment management system developed by **DEV FOUNDRY CO., LTD.**

## 🏗 System Architecture

The system is organized into four core layers to ensure modularity, scalability, and high-performance execution.

### 1. Data Layer (Acquisition)
Responsible for gathering all necessary market information through multiple channels:
* **REST API:** Fetches snapshots of prices, order books, and account balances from Bitkub.
* **WebSocket:** Provides a real-time feed for low-latency price updates.
* **TradingView Integration:** Receives external signals via Webhook alerts.

### 2. Brain Layer (Analysis & Logic)
Processes raw data into actionable insights:
* **Market Analysis:** Scans bid-ask spreads and calculates liquidity gaps.
* **Technical Indicators:** Computes RSI, Moving Averages (MA), Bollinger Bands, and MACD.
* **Signal Aggregator:** Consolidates internal metrics and external signals to feed the **Strategy Engine**.

### 3. Decision Layer (Risk & Control)
The gatekeeper of every trade:
* **Risk Manager:** Enforces strict stop-loss rules and dynamic position sizing.
* **Order Manager:** Handles the logic for placing limit or market orders.
* **Logger:** Maintains a complete audit trail of every decision and system state.

### 4. Execute Layer (Action & Feedback)
Interacts with the exchange and provides real-time monitoring:
* **Bitkub API Bridge:** Executes `place-bid` and `place-ask` requests.
* **Portfolio Tracker:** Calculates real-time P&L and win rates.
* **Notifications:** Sends instant updates and trade summaries via **LINE Messaging API**.

---

## 🚀 Tech Stack
* **Language:** Python 3.8+
* **Libraries:** Pandas (Data Analysis), NumPy (Calculations), Requests
* **API:** Bitkub REST & WebSocket API
* **Notifications:** LINE Messaging API
* **Database:** SQLite / CSV for local logging

## 🛠️ Getting Started

### Prerequisites
* Python 3.8 or higher
* pip (Python package installer)
* Git

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/CodeMePlz-Company/trade_me_plz.git
   cd trade_me_plz
   ```

2. **Setup Environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Configuration:**
   Update your credentials in the `.env` file (refer to `.env.example`).

4. **Run:**
   ```bash
   python main.py
   ```

---

## 👥 Maintainers
* **Nuttida (Jang)** — Co-Founder & CEO

---

© 2026 DEV FOUNDRY CO., LTD. All rights reserved.

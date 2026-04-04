# 🚦 SENTINEL.AI: Real-Time Traffic AI & Monitoring System

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python)
![Streamlit](https://img.shields.io/badge/Streamlit-1.35.0-FF4B4B?style=for-the-badge&logo=streamlit)
![Supabase](https://img.shields.io/badge/Supabase-Database-3ECF8E?style=for-the-badge&logo=supabase)
![Pandas](https://img.shields.io/badge/Pandas-2.2.2-150458?style=for-the-badge&logo=pandas)

SENTINEL.AI is a robust, enterprise-grade AI monitoring and simulation system designed specifically for real-time traffic control environments. It features a complete architecture for generating high-frequency telemetry data, detecting statistical drift, and providing real-time data visualization.

---

## 🚀 Overview

The system aims to tackle the challenges of silent AI failures in traffic control systems. It is divided into two primary subsystems:

1. Traffic AI (`traffic-ai`): A high-frequency traffic phase and queue simulator that models realistic intersections and pushes telemetry log data in real-time.
2. Sentinel AI (`sentinel-ai`): An asynchronous monitoring daemon that actively tracks statistical drift, flags anomalies, and displays insights via a unified live dashboard.

---

## 🧠 Core Architecture & MLOps Features

Sentinel AI uses an advanced Two-Phase State Machine to monitor real-time environments without hardcoded operational thresholds:

- Phase 1: Baseline Learning (Logs 1-200) 
  The engine passively learns the natural rhythm of a junction (e.g., standard queue lengths, phase delays). It calculates and stores the historical Mean ($\mu$) and Standard Deviation ($\sigma$) for critical metrics.
  
- Phase 2: Active Monitoring (Logs 201+) 
  The system enters active tracking. Every new log is compared against the frozen baseline configuration. It generates a live Z-score to represent how drastically the current environment has deviated from historical expectations (Data Drift).

---

## 📂 Repository Structure
SENTINEL.AI/
│
├── traffic-ai/                 # The core Traffic Simulator
│   ├── main.py                 # Traffic AI Data generation engine
│   ├── simulator.py            # Simulation logic
│   ├── dashboard.py            # Local simulator dashboard
│   ├── schema.sql              # Supabase table structures for raw logs
│   ├── requirements.txt        # Simulator dependencies
│   └── .env                    # Local environment variables
│
├── sentinel-ai/                # The Drift & Monitoring Daemon
│   ├── sentinel_main.py        # Central monitoring daemon
│   ├── sentinel_dashboard.py   # Primary Unified Streamlit Dashboard
│   ├── drift_detector.py       # Z-score and statistical drift calculations
│   ├── baseline_engine.py      # Baseline metric computation
│   ├── engine.py               # Aggregation & routing
│   ├── schema.sql              # Supabase table structures for drift insights
│   ├── requirements.txt        # Sentinel dependencies
│   └── (other engine files)    # Specialized alert and logic routing
│
└── README.md                   # Project documentation
---

## 🛠 Getting Started

### Prerequisites

- Python: 3.10 or higher.
- Supabase: A Supabase project set up. You will need your URL and Anon / Service Key.
- Git (optional, but recommended).

### 1. Clone & Setup

Navigate to your workspace and clone/open the repository:
cd SENTINEL.AI
### 2. Configure Environment Variables

Both the traffic-ai and sentinel-ai applications rely on Supabase for robust data persistence. You will need to create a .env file in both directories.

Example .env content:
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-service-key
> Note: Be sure to execute the queries found in schema.sql (in both subdirectories) into your Supabase SQL Editor to correctly initialize your tables!

### 3. Install Dependencies

Install the requirements for both services. We recommend using a Python virtual environment (python -m venv venv).

For Traffic AI:
cd traffic-ai
pip install -r requirements.txt
cd ..

For Sentinel AI:
cd sentinel-ai
pip install -r requirements.txt
cd ..
---

## 🚦 Running the System

To experience the full end-to-end simulation and monitoring flow, you must run several components in parallel.

### Step 1: Start the Traffic Simulator
Open a new terminal and fire up the dummy traffic generation engine:
cd traffic-ai
python main.py
*(This begins seeding Supabase with high-frequency telemetry info).*

### Step 2: Start the Sentinel Monitoring Daemon
Open a second terminal and start the monitoring engine:
cd sentinel-ai
python sentinel_main.py
*(This reads telemetry data, computes sliding windows, builds the baseline, and detects drift).*

### Step 3: Launch the Sentinel Real-Time Dashboard
Open a third terminal, navigate to the Sentinel app, and start the Streamlit UI:
cd sentinel-ai
streamlit run sentinel_dashboard.py
*(Your browser will open automatically displaying real-time metrics, warnings, and Z-score visualization).*

---

## 💻 Tech Stack

- Backend: Python
- Database: Supabase (PostgreSQL)
- Frontend/Dashboard: Streamlit & Plotly
- Data Engineering: Pandas & NumPy

---
*Built for real-world reliability and dynamic anomaly awareness.*
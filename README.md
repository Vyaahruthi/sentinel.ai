# SENTINEL.AI: Traffic Base Model Simulator 🚦

This repository contains the backend data generation and statistical monitoring engine for **SENTINEL.AI**. 

It generates traffic logs for multiple independent junctions and actively calculates statistical data to (Z-scores) in real-time.

---

## 🧠 Core Architecture & Features

This backend is designed with enterprise MLOps principles, featuring a built-in statistical engine to detect silent AI failures.


### 1. Two-Phase State Machine
To accurately detect anomalies without hardcoded thresholds, the engine operates in two distinct phases:
* **Phase 1: Baseline Learning (Logs 1-200)** The system quietly observes the data stream to learn the natural rhythm of the junction. It calculates and freezes the historical Mean ($\mu$) and Standard Deviation ($\sigma$) for key metrics.
* **Phase 2: Active Monitoring (Logs 201+)** The system shifts to monitoring mode. Every new log is compared against the frozen baseline to calculate a dynamic Z-score, representing how far the AI's current environment has drifted from reality.
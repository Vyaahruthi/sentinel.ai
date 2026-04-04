import os
import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta

from backend.database import get_recent_logs
from sentinel.sentinel_engine import evaluate_system, THRESHOLDS
from sentinel.drift_detectors import detect_drifts
from pydantic import BaseModel

class ExplainRequest(BaseModel):
    alerts: list[str]
    metrics: dict

app = FastAPI(title="Sentinel AI - Traffic API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"status": "Sentinel AI API Running"}

@app.get("/baseline-status")
def fetch_baseline_status():
    """Returns the dynamic baseline learning status and thresholds."""
    from backend.baseline_learner import collector, ThresholdLearner
    learner = ThresholdLearner(collector)
    stats = learner.get_thresholds()
    
    samples = stats['sample_size']
    learning_progress = min(100, int((samples / 30) * 100))
    
    original_high = 0.8
    original_medium = 0.6
    shift_high = round(stats['high_threshold'] - original_high, 3)
    shift_medium = round(stats['medium_threshold'] - original_medium, 3)
    
    return {
        "mode": stats['mode'],
        "sample_size": samples,
        "required_samples": 30,
        "learning_progress_percent": learning_progress,
        "baseline_mean": round(stats['baseline_mean'], 3),
        "baseline_std": round(stats['baseline_std'], 3),
        "high_threshold": round(stats['high_threshold'], 3),
        "medium_threshold": round(stats['medium_threshold'], 3),
        "threshold_floors_applied": stats['threshold_floors_applied'],
        "threshold_ceilings_applied": stats['threshold_ceilings_applied'],
        "original_high_threshold": original_high,
        "original_medium_threshold": original_medium,
        "threshold_shift_high": f"{shift_high:+.3f}",
        "threshold_shift_medium": f"{shift_medium:+.3f}"
    }

@app.get("/logs")
def fetch_logs(limit: int = 200):
    """Fetch the most recent raw traffic logs."""
    logs = get_recent_logs(limit)
    return {"logs": logs}

@app.get("/metrics")
def fetch_metrics():
    """Evaluate system drift and return current status, metrics, and alerts."""
    return evaluate_system()

@app.post("/explain")
def explain_anomalies(request: ExplainRequest):
    """Fetch Gemini explanation for specific alerts and metrics."""
    from sentinel.gemini_explainer import get_explanation
    return get_explanation(request.alerts, request.metrics)

class ResolutionRequest(BaseModel):
    alert_text: str
    alert_type: str = ""
    status: str
    operator_notes: str = ""

@app.get("/resolutions")
def fetch_resolutions():
    """Fetch previously resolved alerts from Supabase."""
    from backend.database import get_resolved_alerts
    resolutions = get_resolved_alerts()
    return {"resolved_alerts": resolutions}

@app.post("/resolutions")
def add_resolution(request: ResolutionRequest):
    """Save a human-in-the-loop resolution to Supabase."""
    from backend.database import insert_alert_resolution
    data = {
        "alert_text": request.alert_text,
        "alert_type": request.alert_type,
        "status": request.status,
        "operator_notes": request.operator_notes
    }
    result = insert_alert_resolution(data)
    return {"status": "success", "data": result.data if hasattr(result, 'data') else result}

@app.get("/audit")
def fetch_audit_log():
    """Fetch all alert resolution records for the audit log."""
    from backend.database import get_all_resolutions
    rows = get_all_resolutions()
    return {"audit_log": rows}


# ---------------------------------------------------------------------------
# Drift Simulation – What-If Endpoint
# ---------------------------------------------------------------------------

class SimulateRequest(BaseModel):
    traffic_volume: int = 298
    active_lanes: int = 3
    accident_active: bool = False
    event_traffic_active: bool = False


def _evaluate_z_scores(metrics: dict, mean: dict, std: dict) -> list[str]:
    """Evaluate a metrics dict against Z-scores and return list of triggered alert type keys."""
    from sentinel.baseline_engine import compute_z_scores, ZSCORE_ALERT_THRESHOLD, METRIC_KEYS
    z_scores = compute_z_scores(metrics, mean, std)
    triggered = []
    for key in METRIC_KEYS:
        z = z_scores.get(key)
        if z is not None and abs(z) >= ZSCORE_ALERT_THRESHOLD:
            triggered.append(key)
    return triggered


@app.post("/simulate-drift")
def simulate_drift(request: SimulateRequest):
    """
    Read-only what-if simulation.
    Generates 50 synthetic rows from user parameters, appends them to the tail
    of the real 500-row baseline, runs detect_drifts on both, and compares.
    Nothing is written to the database.
    """
    # 1. Fetch real baseline
    logs = get_recent_logs(limit=500)
    if not logs:
        return {"error": "No baseline data available. Need at least 50 logs."}

    baseline_df = pd.DataFrame(logs)

    # 2. Build 50 synthetic rows
    n = 50
    tv = request.traffic_volume
    al = request.active_lanes

    now = datetime.now(timezone.utc)
    timestamps = [(now + timedelta(seconds=30 * i)).isoformat() for i in range(n)]

    traffic_vals = tv + np.random.normal(0, tv * 0.05, n)
    traffic_vals = np.round(traffic_vals).astype(int)

    cong_raw = tv / (al * 120.0) + np.random.normal(0, 0.05, n)
    cong_vals = np.clip(cong_raw, 0, 5)

    # Sample junction_type from the real distribution
    jt_distribution = baseline_df['junction_type'].value_counts(normalize=True)
    junction_types = np.random.choice(
        jt_distribution.index, size=n, p=jt_distribution.values
    )

    incident_vals = [True] * n if request.accident_active else [False] * n

    if request.accident_active:
        reason_vals = ["Simulated accident"] * n
    elif request.event_traffic_active:
        reason_vals = ["Event traffic surge"] * n
    else:
        reason_vals = ["Simulation"] * n

    synthetic_df = pd.DataFrame({
        "event_time": timestamps,
        "traffic": traffic_vals,
        "congestion_index": cong_vals,
        "active_lanes": [al] * n,
        "junction_type": junction_types,
        "incident": incident_vals,
        "reason": reason_vals,
    })

    # 3. Combine: real baseline + synthetic at the TAIL
    combined_df = pd.concat([baseline_df, synthetic_df], ignore_index=True)

    # 4. Run drift detection on both
    baseline_metrics = detect_drifts(baseline_df)
    simulated_metrics = detect_drifts(combined_df)

    # 5. Evaluate Z-scores for alerts
    from sentinel.baseline_engine import get_baseline_status
    state = get_baseline_status()
    mean = state.get("baseline_mean", {})
    std = state.get("baseline_std", {})

    baseline_alerts = _evaluate_z_scores(baseline_metrics, mean, std)
    simulated_alerts = _evaluate_z_scores(simulated_metrics, mean, std)

    newly_triggered = [a for a in simulated_alerts if a not in baseline_alerts]
    resolved_by_simulation = [a for a in baseline_alerts if a not in simulated_alerts]

    return {
        "baseline_metrics": baseline_metrics,
        "simulated_metrics": simulated_metrics,
        "baseline_alerts": baseline_alerts,
        "simulated_alerts": simulated_alerts,
        "newly_triggered": newly_triggered,
        "resolved_by_simulation": resolved_by_simulation,
    }


# Run with: uvicorn api.main:app --reload

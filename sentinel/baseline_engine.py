import os
import numpy as np
from datetime import datetime, timezone

from backend.database import get_baseline_state, upsert_baseline_state, get_recent_threshold_history

BASELINE_MIN_RUNS = 200  # minimum evaluations before baseline is locked
ZSCORE_ALERT_THRESHOLD = float(os.getenv("ZSCORE_THRESHOLD", "2.0"))

METRIC_KEYS = [
    "behaviour_adaptation",
    "data_bias",
    "data_drift",
    "feedback_loop",
    "silent_drift",
    "infrastructure_change",
    "policy_change",
    "technology_influence",
    "event_traffic"
]

def update_baseline(new_metrics: dict, junction_id: str) -> dict:
    state = get_baseline_state()
    current_run_count = state.get("run_count", 0)
    new_run_count = current_run_count + 1
    
    # Fetch threshold history for computing mean and std
    raw_history = get_recent_threshold_history(limit=600) # Increased limit to capture enough per-junction rows
    
    # Filter history down to only rows strictly matching this junction_id
    history = [row for row in raw_history if row.get("z_scores") and isinstance(row.get("z_scores"), dict) and row["z_scores"].get("junction_id") == junction_id]

    # Initialize nested JSON structures if they don't exist
    baseline_mean_full = state.get("baseline_mean") or {}
    baseline_std_full = state.get("baseline_std") or {}
    baseline_quality_full = state.get("baseline_quality") or {}
    
    junction_mean = {}
    junction_std = {}
    junction_quality = {}

    for key in METRIC_KEYS:
        # Extract values ignoring Nones
        values = [row.get(key) for row in history if row.get(key) is not None]
        
        if len(values) >= 5:
            mean = float(np.mean(values))
            calc_std = float(np.std(values))
            
            # Epsilon fix depending on metric type
            raw_count_metrics = ["event_traffic", "technology_influence", "infrastructure_change", "data_drift"]
            if key in raw_count_metrics:
                std = max(calc_std, 5.0)
            else:
                std = max(calc_std, 0.05)
                
            junction_mean[key] = round(mean, 6)
            junction_std[key] = round(std, 6)
            
            # calculate quality
            cv = std / mean if mean != 0 else None
            junction_quality[key] = {
                "sample_size": len(values),
                "coefficient_of_variation": round(cv, 4) if cv else None,
                "is_stable": (cv < 0.5) if (cv is not None) else False
            }
        else:
            junction_mean[key] = None
            junction_std[key] = None
            junction_quality[key] = {
                "sample_size": len(values),
                "coefficient_of_variation": None,
                "is_stable": False
            }

    # Store specifically into this junction's slice
    baseline_mean_full[junction_id] = junction_mean
    baseline_std_full[junction_id] = junction_std
    baseline_quality_full[junction_id] = junction_quality

    # Lock baseline automatically once 200 ticks hit (assumes 1 simultaneous tick = 1 run_count)
    baseline_locked = new_run_count >= BASELINE_MIN_RUNS
    
    update_payload = {
        "id": state.get("id", "00000000-0000-0000-0000-000000000001"),
        "run_count": new_run_count,
        "baseline_locked": baseline_locked,
        "baseline_mean": baseline_mean_full,
        "baseline_std": baseline_std_full,
        "baseline_quality": baseline_quality_full,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

    if baseline_locked and not state.get("baseline_locked", False):
        print(f"Sentinel baseline LOCKED after {new_run_count} evaluation runs.")
    
    upsert_baseline_state(update_payload)
    return update_payload


def compute_z_scores(metrics: dict, baseline_mean_full: dict, baseline_std_full: dict, junction_id: str) -> dict:
    """
    For each metric, compute Z = (current_value - baseline_mean) / baseline_std specific to junction_id.
    Returns dict of z_scores per metric.
    """
    z_scores = {"junction_id": junction_id}
    
    j_mean = baseline_mean_full.get(junction_id, {})
    j_std = baseline_std_full.get(junction_id, {})
    
    for key in METRIC_KEYS:
        current = metrics.get(key)
        mean = j_mean.get(key)
        std = j_std.get(key)
        
        if current is None or mean is None or std is None or std == 0:
            z_scores[key] = None
            continue
            
        # For metrics where magnitude matters (not direction)
        if key in ("behaviour_adaptation", "silent_drift"):
            z_scores[key] = round((abs(current) - abs(mean)) / std, 4)
        else:
            z_scores[key] = round((current - mean) / std, 4)
            
    return z_scores


def get_baseline_status() -> dict:
    state = get_baseline_state()
    run_count = state.get("run_count", 0)
    baseline_locked = state.get("baseline_locked", False)
    
    progress = 100 if baseline_locked else min(int(run_count / BASELINE_MIN_RUNS * 100), 100)
    
    return {
        "run_count": run_count,
        "baseline_locked": baseline_locked,
        "baseline_mean": state.get("baseline_mean", {}),
        "baseline_std": state.get("baseline_std", {}),
        "baseline_quality": state.get("baseline_quality", {}),
        "learning_progress": progress,
        "mode": "active" if baseline_locked else "learning"
    }


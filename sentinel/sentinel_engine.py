import os
import sys
import hashlib
import pandas as pd
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import get_recent_logs, insert_threshold_history
from sentinel.drift_detectors import detect_drifts
from sentinel.baseline_engine import (
    update_baseline,
    compute_z_scores,
    get_baseline_status,
    BASELINE_MIN_RUNS,
    ZSCORE_ALERT_THRESHOLD,
    METRIC_KEYS
)

# Define thresholds for the 9 metrics to trigger alerts
THRESHOLDS = {
    "behaviour_adaptation": {"max_abs": 0.05, "name": "Behaviour adaptation risk"},
    "data_bias": {"max": 1.5, "name": "High data bias"},
    "data_drift": {"max": 50.0, "name": "Data drift detected"},
    "feedback_loop": {"min": 0.95, "name": "Feedback loop risk (High correlation)"},
    "silent_drift": {"max_abs": 1.0, "name": "Silent drift trending"},
    "infrastructure_change": {"max": 10.0, "name": "Infrastructure usage shift"},
    "policy_change": {"max": 0.2, "name": "Policy impact detected"},
    "technology_influence": {"max": 5, "name": "Unusual technology/app influence spikes"},
    "event_traffic": {"max": 10, "name": "High event-driven traffic"}
}


def _make_alert_id(alert_type: str) -> str:
    """Generate a deterministic alert ID based on the alert type."""
    return hashlib.md5(alert_type.encode()).hexdigest()[:12]


def evaluate_system():
    """
    Fetches the latest logs, runs detectors, evaluates thresholds, and returns
    structured alert objects alongside metrics.
    """
    print(f"evaluate_system() called at {datetime.now(timezone.utc).isoformat()}")
    
    logs = get_recent_logs(limit=500)
    if not logs:
        return {
            "status": "No data",
            "metrics": {},
            "alerts": [],
            "logs_count": 0
        }
        
    df = pd.DataFrame(logs)
    
    # ── Schema Normalization ─────────────────
    # The drift detectors expect `event_time`, `traffic`, `active_lanes`, `congestion_index`, `incident`, `reason`.
    # Our `traffic_logs` table provides `timestamp`, `traffic_volume`, `is_peak_hour`, `is_event`, `has_incident`.
    if not df.empty:
        if 'timestamp' in df.columns:
            df['event_time'] = df['timestamp']
        if 'traffic_volume' in df.columns:
            df['traffic'] = df['traffic_volume']
        if 'has_incident' in df.columns:
            df['incident'] = df['has_incident']
            
        # Synthesize derived metrics required by drift_detectors natively
        if 'active_lanes' not in df.columns:
            df['active_lanes'] = df['traffic'].apply(lambda x: 3 if x > 200 else (2 if x > 100 else 1))
        if 'congestion_index' not in df.columns:
            df['congestion_index'] = df['traffic'] / (df['active_lanes'] * 120)
        if 'junction_type' not in df.columns:
            df['junction_type'] = df['junction_id'].map({"J1": "highway", "J2": "intersection", "J3": "roundabout"})
        if 'reason' not in df.columns:
            df['reason'] = df.apply(lambda row: "Simulated accident" if row.get("has_incident") else ("Peak hour rush" if row.get("is_peak_hour") else "Normal flow"), axis=1)

    # ── Baseline learning and Z-score computation ─────────────────
    baseline_state = get_baseline_status()
    baseline_mean_full = baseline_state.get("baseline_mean", {})
    baseline_std_full = baseline_state.get("baseline_std", {})
    baseline_locked = baseline_state.get("baseline_locked", False)
    run_count = baseline_state.get("run_count", 0)

    # Output aggregators
    all_alerts = []
    global_status = "Active"
    global_ai_locked = False
    
    # We will compute metrics and z_scores per-junction for the return payload 
    # so the API continues functioning perfectly for the frontend.
    master_metrics = {}
    master_z_scores = {}
    
    junctions = df['junction_id'].unique() if 'junction_id' in df.columns else ["J1"]
    
    for j_id in junctions:
        j_df = df[df['junction_id'] == j_id] if 'junction_id' in df.columns else df
        
        # Don't evaluate empty or strictly insufficient arrays
        if len(j_df) < 20: continue
            
        metrics = detect_drifts(j_df)
        z_scores = compute_z_scores(metrics, baseline_mean_full, baseline_std_full, j_id)
        
        master_metrics[j_id] = metrics
        master_z_scores[j_id] = z_scores

        if not baseline_locked:
            # Store threshold history with no alerts FIRST
            insert_threshold_history({
                "computed_at": datetime.now(timezone.utc).isoformat(),
                **metrics,
                "z_scores": z_scores,
                "baseline_mean": baseline_mean_full,
                "baseline_std": baseline_std_full,
                "baseline_locked": baseline_locked,
                "baseline_run_count": run_count
            })
            
            # Update baseline with new data point
            update_baseline(metrics, j_id)
            continue
            
        seen_types = set()
        
        for key in METRIC_KEYS:
            z = z_scores.get(key)
            if z is None:
                continue
                
            abs_z = abs(z)
            if abs_z >= 2.0 and key not in seen_types:
                seen_types.add(key)
                
                val = metrics.get(key, 0.0)
                mean = baseline_mean_full.get(j_id, {}).get(key, 0.0)
                std = baseline_std_full.get(j_id, {}).get(key, 1.0)
                
                message = (
                    f"{THRESHOLDS[key]['name']} at {j_id} — "
                    f"Z-score: {z:.2f} "
                    f"(current: {val:.4f}, baseline mean: {mean:.4f}, "
                    f"std: {std:.4f}). "
                    f"Value is {abs_z:.1f} standard deviations from normal."
                )
                
                alert = {
                    "id": _make_alert_id(f"{key}_{j_id}_{run_count}"),
                    "type": key,
                    "junction": j_id,
                    "message": message,
                    "z_score": z,
                    "current_value": round(val, 4),
                    "baseline_mean": round(mean, 4),
                    "baseline_std": round(std, 4),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                
                # Application of Tiering Logic
                if 2.0 <= abs_z < 2.3:
                    alert["tier"] = 1
                    alert["action"] = "Auto-acknowledged"
                    alert["monitor_frequency_multiplier"] = 2
                    
                elif 2.3 <= abs_z <= 3.0:
                    alert["tier"] = 2
                    alert["action"] = "Requires Human Operator"
                    alert["status"] = "pending_human_approval"
                    alert["correction_proposal"] = f"Adjust system weights for {key} at {j_id} to counter a {abs_z:.1f} sigma drift."
                    if global_status != "active_sos_incident":
                        global_status = "pending_human_approval"
                else:
                    alert["tier"] = 3
                    alert["action"] = "Human REQUIRED"
                    alert["status"] = "active_sos_incident"
                    alert["ai_action_taken"] = False
                    global_status = "active_sos_incident"
                    global_ai_locked = True
                    
                all_alerts.append(alert)

        if baseline_locked:
            # Store threshold history for this run
            insert_threshold_history({
                "computed_at": datetime.now(timezone.utc).isoformat(),
                **metrics,
                "z_scores": z_scores,
                "baseline_mean": baseline_mean_full,
                "baseline_std": baseline_std_full,
                "baseline_locked": baseline_locked,
                "baseline_run_count": run_count
            })
            
            # Update baseline with new data point
            update_baseline(metrics, j_id)
            
    if not baseline_locked:
        return {
            "status": "Learning",
            "mode": "baseline_learning",
            "metrics": master_metrics,
            "z_scores": master_z_scores,
            "alerts": [],
            "logs_count": len(df),
            "message": f"Building baseline — {run_count}/{BASELINE_MIN_RUNS} evaluation runs complete. No alerts fired during learning phase.",
            "baseline": {
                "run_count": run_count,
                "locked": baseline_locked,
                "learning_progress": min(int(run_count / BASELINE_MIN_RUNS * 100), 99),
                "quality": baseline_state.get("baseline_quality", {}),
                "mean": baseline_mean_full
            }
        }

    return {
        "status": global_status,
        "ai_locked": global_ai_locked,
        "mode": "active",
        "metrics": master_metrics,
        "z_scores": master_z_scores,
        "alerts": all_alerts,
        "logs_count": len(df),
        "baseline": {
            "run_count": run_count,
            "locked": baseline_locked,
            "learning_progress": 100,
            "quality": baseline_state.get("baseline_quality", {}),
            "mean": baseline_mean_full
        }
    }

if __name__ == "__main__":
    result = evaluate_system()
    print("Metrics:", result["metrics"])
    print("Alerts:", result["alerts"])

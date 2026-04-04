"""
Compute all 9 sentinel parameter values from traffic-ai tables.
Each function returns: {value: float, reason: str, context: dict}
"""
import numpy as np
import pandas as pd
from datetime import datetime, timezone

PARAMETER_NAMES = [
    "behaviour_adaptation",
    "data_bias",
    "data_drift",
    "feedback_loop",
    "silent_drift",
    "infrastructure_change",
    "policy_change",
    "technology_influence",
    "event_traffic",
]

PARAMETER_DESCRIPTIONS = {
    "behaviour_adaptation":  "How rapidly the AI is changing its lane decisions",
    "data_bias":             "Systematic skew of recent traffic vs historical mean",
    "data_drift":            "Distribution shift — variance ratio recent vs historical",
    "feedback_loop":         "Same lane decision repeating consecutively (locked state)",
    "silent_drift":          "Slow cumulative drift below normal alert threshold (CUSUM)",
    "infrastructure_change": "Step change in traffic baseline suggesting road/capacity change",
    "policy_change":         "Decisions decoupling from traffic — external policy shift",
    "technology_influence":  "Data quality degradation — outlier rate and sensor gaps",
    "event_traffic":         "Event-driven traffic spikes above normal operating range",
}


def _fetch_logs(client, junction_id: str, limit: int = 100) -> pd.DataFrame:
    try:
        res = (
            client.table("traffic_logs")
            .select("*")
            .eq("junction_id", junction_id)
            .order("timestamp", desc=True)
            .limit(limit)
            .execute()
        )
        df = pd.DataFrame(res.data or [])
        if not df.empty:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            if "traffic_volume" in df.columns:
                df["traffic"] = df["traffic_volume"]
            if "is_event" in df.columns and "is_peak_hour" in df.columns:
                df["event_type"] = df.apply(lambda x: "event" if x.get("is_event", False) else ("peak_hour" if x.get("is_peak_hour", False) else "normal"), axis=1)
        return df
    except Exception as e:
        print(f"[params] Fetch logs failed: {e}")
        return pd.DataFrame()


def _fetch_decisions(client, junction_id: str, limit: int = 100) -> pd.DataFrame:
    try:
        res = (
            client.table("decisions")
            .select("*")
            .eq("junction_id", junction_id)
            .order("timestamp", desc=True)
            .limit(limit)
            .execute()
        )
        df = pd.DataFrame(res.data or [])
        if not df.empty:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            if "lanes_allocated" in df.columns:
                df["lanes"] = df["lanes_allocated"]
        return df
    except Exception as e:
        print(f"[params] Fetch decisions failed: {e}")
        return pd.DataFrame()


# ─── 1. Behaviour Adaptation ─────────────────────────────────────────────────
def _behaviour_adaptation(decisions: pd.DataFrame) -> dict:
    if len(decisions) < 10:
        return {"value": 0.0, "reason": "Insufficient data", "context": {}}
    changes = decisions["lanes"].astype(float).diff().abs().dropna()
    value   = float(changes.mean())
    if value < 0.3:
        reason = "Decision pattern is stable — no unusual adaptation"
    elif value < 0.6:
        reason = f"Frequent minor adjustments detected (avg change={value:.2f} lanes/tick)"
    else:
        reason = f"Heavy adaptation — AI decisions changing rapidly ({value:.2f} lanes/tick avg)"
    return {"value": value, "reason": reason,
            "context": {"avg_lane_change": round(value, 4), "samples": len(changes)}}


# ─── 2. Data Bias ─────────────────────────────────────────────────────────────
def _data_bias(logs: pd.DataFrame) -> dict:
    if len(logs) < 20:
        return {"value": 0.0, "reason": "Insufficient data", "context": {}}
    recent_mean = logs.head(20)["traffic"].mean()
    hist_mean   = logs["traffic"].mean()
    std         = max(logs["traffic"].std(), 1.0)
    value       = float((recent_mean - hist_mean) / std)
    direction   = "upward" if value > 0 else "downward"
    if abs(value) < 0.5:
        reason = f"No systematic bias — recent mean {recent_mean:.0f} aligns with baseline {hist_mean:.0f}"
    else:
        reason = (f"Systematic {direction} bias — recent avg {recent_mean:.0f} "
                  f"vs baseline {hist_mean:.0f} ({abs(value):.2f}σ)")
    return {"value": value, "reason": reason,
            "context": {"recent_mean": round(recent_mean, 2),
                        "hist_mean":   round(hist_mean, 2),
                        "sigma_diff":  round(abs(value), 3)}}


# ─── 3. Data Drift ────────────────────────────────────────────────────────────
def _data_drift(logs: pd.DataFrame) -> dict:
    if len(logs) < 30:
        return {"value": 0.0, "reason": "Insufficient data", "context": {}}
    recent_var = max(logs.head(20)["traffic"].var(), 1e-6)
    hist_var   = max(logs["traffic"].var(), 1e-6)
    ratio      = recent_var / hist_var
    value      = float(np.log(ratio))      # log ratio: symmetric around 0
    if abs(value) < 0.3:
        reason = "Distribution stable — variance consistent with baseline"
    elif value > 0:
        reason = (f"Variance expanding ({ratio:.2f}x baseline) — "
                  f"traffic becoming more unpredictable")
    else:
        reason = (f"Variance contracting ({ratio:.2f}x baseline) — "
                  f"unusual traffic homogeneity detected")
    return {"value": value, "reason": reason,
            "context": {"recent_var": round(recent_var, 2),
                        "hist_var":   round(hist_var, 2),
                        "var_ratio":  round(ratio, 3)}}


# ─── 4. Feedback Loop ─────────────────────────────────────────────────────────
def _feedback_loop(decisions: pd.DataFrame) -> dict:
    if len(decisions) < 5:
        return {"value": 0.0, "reason": "Insufficient data", "context": {}}
    # Convert 'lanes' to list if not already
    lanes = decisions.head(30)["lanes"].tolist()
    max_streak = cur = 1
    for i in range(1, len(lanes)):
        cur = cur + 1 if lanes[i] == lanes[i-1] else 1
        max_streak = max(max_streak, cur)
    value = float(max_streak)
    if max_streak < 5:
        reason = "No feedback loop — lane decisions varying normally"
    elif max_streak < 10:
        reason = (f"Moderate feedback loop — same decision repeated "
                  f"{max_streak} consecutive ticks ({lanes[0]} lanes)")
    else:
        reason = (f"Strong feedback loop — decision locked at {lanes[0]} lanes "
                  f"for {max_streak} ticks. Possible reinforcement issue.")
    return {"value": value, "reason": reason,
            "context": {"max_streak": max_streak,
                        "locked_lane": lanes[0] if lanes else None}}


# ─── 5. Silent Drift (CUSUM) ──────────────────────────────────────────────────
def _silent_drift(logs: pd.DataFrame) -> dict:
    if len(logs) < 30:
        return {"value": 0.0, "reason": "Insufficient data", "context": {}}
    series     = logs["traffic"].values[::-1]   # chronological order
    ref_window = series[:min(50, len(series))]
    mean       = np.mean(ref_window)
    std        = max(np.std(ref_window), 1.0)
    k = 0.5
    cusum_pos = cusum_neg = 0.0
    for v in series[-30:]:
        z = (v - mean) / std
        cusum_pos = max(0.0, cusum_pos + z - k)
        cusum_neg = max(0.0, cusum_neg - z - k)
    value = float(max(cusum_pos, cusum_neg))
    if value < 3:
        reason = "No silent drift — CUSUM within normal bounds"
    elif cusum_pos > cusum_neg:
        reason = (f"Gradual upward drift accumulating (CUSUM={value:.2f}) — "
                  f"not yet at Z-score threshold but trending up")
    else:
        reason = (f"Gradual downward drift accumulating (CUSUM={value:.2f}) — "
                  f"slow decline below baseline")
    return {"value": value, "reason": reason,
            "context": {"cusum_pos": round(cusum_pos, 3),
                        "cusum_neg": round(cusum_neg, 3),
                        "ref_mean":  round(mean, 2)}}


# ─── 6. Infrastructure Change ─────────────────────────────────────────────────
def _infrastructure_change(logs: pd.DataFrame) -> dict:
    if len(logs) < 20:
        return {"value": 0.0, "reason": "Insufficient data", "context": {}}
    half         = len(logs) // 2
    recent_mean  = logs.head(half)["traffic"].mean()
    older_mean   = logs.tail(half)["traffic"].mean()
    std          = max(logs["traffic"].std(), 1.0)
    value        = float(abs(recent_mean - older_mean) / std)
    if value < 1.0:
        reason = "No infrastructure change detected — baseline stable"
    elif value < 2.0:
        reason = (f"Possible infrastructure change — traffic mean shifted "
                  f"{value:.1f}σ between halves ({older_mean:.0f} → {recent_mean:.0f})")
    else:
        reason = (f"Strong infrastructure change signal — {value:.1f}σ step change. "
                  f"Possible road capacity or sensor reconfiguration.")
    return {"value": value, "reason": reason,
            "context": {"recent_mean": round(recent_mean, 2),
                        "older_mean":  round(older_mean, 2),
                        "step_sigma":  round(value, 3)}}


# ─── 7. Policy Change ─────────────────────────────────────────────────────────
def _policy_change(decisions: pd.DataFrame, logs: pd.DataFrame) -> dict:
    if len(decisions) < 15 or len(logs) < 15:
        return {"value": 0.0, "reason": "Insufficient data", "context": {}}
    n      = min(len(decisions), len(logs), 20)
    lanes  = decisions.head(n)["lanes"].values.astype(float)
    traffic = logs.head(n)["traffic"].values.astype(float)
    if len(lanes) != len(traffic):
        n = min(len(lanes), len(traffic))
        lanes, traffic = lanes[:n], traffic[:n]
    if np.std(traffic) < 1:
        return {"value": 0.0, "reason": "Low traffic variance — cannot measure policy correlation",
                "context": {}}
    corr  = float(np.corrcoef(traffic, lanes)[0, 1])
    value = float(1.0 - abs(corr))   # 0 = normal, 1 = fully decoupled
    if value < 0.3:
        reason = f"Decisions tracking traffic normally (corr={corr:.2f})"
    elif value < 0.6:
        reason = (f"Partial policy shift — decisions partially decoupled "
                  f"from traffic (corr={corr:.2f})")
    else:
        reason = (f"Policy change detected — lane decisions largely independent "
                  f"of traffic levels (corr={corr:.2f}). External rule change?")
    return {"value": value, "reason": reason,
            "context": {"traffic_lane_corr": round(corr, 3),
                        "decoupling_score":  round(value, 3)}}


# ─── 8. Technology Influence ──────────────────────────────────────────────────
def _technology_influence(logs: pd.DataFrame) -> dict:
    if len(logs) < 10:
        return {"value": 0.0, "reason": "Insufficient data", "context": {}}
    traffic      = logs["traffic"]
    mean         = traffic.mean()
    std          = max(traffic.std(), 1.0)
    z_scores     = ((traffic - mean) / std).abs()
    outlier_cnt  = int((z_scores > 3).sum())
    outlier_rate = outlier_cnt / len(traffic)
    gap_score    = 0.0
    if "timestamp" in logs.columns and len(logs) > 2:
        ts     = logs["timestamp"].sort_values()
        diffs  = ts.diff().dropna().dt.total_seconds()
        median = diffs.median()
        if median > 0:
            large_gaps = int((diffs > median * 5).sum())
            gap_score  = large_gaps / max(len(diffs), 1)
    value = float(outlier_rate + gap_score)
    if value < 0.05:
        reason = "Data quality normal — no sensor or transmission issues"
    elif value < 0.15:
        reason = (f"Minor data quality issues — {outlier_cnt} outliers, "
                  f"{gap_score:.0%} timestamp gap rate")
    else:
        reason = (f"Significant data quality degradation — {outlier_cnt} outliers "
                  f"({outlier_rate:.0%} rate). Possible sensor malfunction.")
    return {"value": value, "reason": reason,
            "context": {"outlier_count": outlier_cnt,
                        "outlier_rate":  round(outlier_rate, 4),
                        "gap_score":     round(gap_score, 4)}}


# ─── 9. Event Traffic ─────────────────────────────────────────────────────────
def _event_traffic(logs: pd.DataFrame) -> dict:
    if len(logs) < 10:
        return {"value": 0.0, "reason": "Insufficient data", "context": {}}
    
    if "event_type" not in logs.columns:
        return {"value": 0.0, "reason": "event_type not available in logs", "context": {}}
        
    event_rows   = logs[logs["event_type"].isin(["event", "peak_hour"])]
    event_rate   = len(event_rows) / len(logs)
    normal_rows  = logs[~logs["event_type"].isin(["event", "peak_hour"])]
    if len(event_rows) > 0 and len(normal_rows) > 0:
        event_mean  = event_rows["traffic"].mean()
        normal_mean = normal_rows["traffic"].mean()
        std         = max(logs["traffic"].std(), 1.0)
        intensity   = (event_mean - normal_mean) / std
        value       = float(max(intensity * event_rate * 10, 0))
    else:
        value, intensity = 0.0, 0.0
    if value < 1:
        reason = "No significant event traffic — normal operating conditions"
    elif value < 3:
        reason = (f"Moderate event traffic — {event_rate:.0%} event rate "
                  f"with {intensity:.1f}σ intensity above normal")
    else:
        reason = (f"Heavy event-driven traffic — {event_rate:.0%} of ticks are "
                  f"event-type with {intensity:.1f}σ above normal baseline")
    return {"value": value, "reason": reason,
            "context": {"event_rate":    round(event_rate, 3),
                        "event_count":   int(len(event_rows)),
                        "intensity_sigma": round(intensity, 3)}}


# ─── Master function ──────────────────────────────────────────────────────────
def compute_all_parameters(client, junction_id: str) -> dict:
    logs      = _fetch_logs(client, junction_id, limit=100)
    decisions = _fetch_decisions(client, junction_id, limit=100)
    if logs.empty:
        return {p: {"value": 0.0, "reason": "No traffic data", "context": {}}
                for p in PARAMETER_NAMES}
    return {
        "behaviour_adaptation":  _behaviour_adaptation(decisions),
        "data_bias":             _data_bias(logs),
        "data_drift":            _data_drift(logs),
        "feedback_loop":         _feedback_loop(decisions),
        "silent_drift":          _silent_drift(logs),
        "infrastructure_change": _infrastructure_change(logs),
        "policy_change":         _policy_change(decisions, logs),
        "technology_influence":  _technology_influence(logs),
        "event_traffic":         _event_traffic(logs),
    }

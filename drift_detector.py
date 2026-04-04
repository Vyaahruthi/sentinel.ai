"""
For each parameter: store observation, compute Z-score, assign tier, store drift event.
"""
from datetime import datetime, timezone
from baseline_engine import get_latest_baseline, compute_z_score, compute_confidence

TIER_THRESHOLDS = {1: 2.0, 2: 2.5, 3: 3.0}

# Hysteresis: an active event only resolves once Z drops this far BELOW the T1 trigger.
# Prevents instant resolve when Z briefly dips under the threshold.
RESOLVE_HYSTERESIS_Z = 1.2

PARAMETER_LABELS = {
    "behaviour_adaptation":  "Behaviour Adaptation",
    "data_bias":             "Data Bias",
    "data_drift":            "Data Drift",
    "feedback_loop":         "Feedback Loop",
    "silent_drift":          "Silent Drift",
    "infrastructure_change": "Infrastructure Change",
    "policy_change":         "Policy Change",
    "technology_influence":  "Technology Influence",
    "event_traffic":         "Event Traffic",
}


def assign_tier(z_score: float) -> int:
    az = abs(z_score)
    if az >= TIER_THRESHOLDS[3]: return 3
    if az >= TIER_THRESHOLDS[2]: return 2
    if az >= TIER_THRESHOLDS[1]: return 1
    return 0


def store_observation(client, junction_id: str, parameter: str,
                       value: float, context: dict):
    try:
        client.table("sentinel_observations").insert({
            "junction_id": junction_id,
            "parameter":   parameter,
            "value":       value,
            "raw_context": context,
        }).execute()
    except Exception as e:
        print(f"[detector] Obs store failed {parameter}: {e}")


def get_active_event(client, junction_id: str, parameter: str) -> dict | None:
    """Return the currently active drift event for this junction+parameter, or None."""
    try:
        res = (
            client.table("drift_events")
            .select("*")
            .eq("junction_id", junction_id)
            .eq("parameter",   parameter)
            .eq("status",      "active")
            .order("detected_at", desc=True)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None
    except Exception as e:
        print(f"[detector] get_active_event failed: {e}")
        return None


def update_drift_event(client, event_id: str,
                        z_score: float, confidence: float,
                        tier: int, current_value: float) -> None:
    """Refresh z_score / tier on an already-active event (no new row created)."""
    try:
        client.table("drift_events").update({
            "z_score":       round(z_score, 4),
            "confidence":    confidence,
            "tier":          tier,
            "current_value": current_value,
        }).eq("id", event_id).execute()
    except Exception as e:
        print(f"[detector] update_drift_event failed: {e}")


def store_drift_event(client, junction_id: str, parameter: str,
                       current_value: float, baseline: dict,
                       z_score: float, confidence: float,
                       tier: int, reason: str) -> dict | None:
    row = {
        "junction_id":   junction_id,
        "parameter":     parameter,
        "current_value": current_value,
        "baseline_mean": baseline["mean"],
        "baseline_std":  baseline["std"],
        "z_score":       round(z_score, 4),
        "confidence":    confidence,
        "tier":          tier,
        "reason":        reason,
        "status":        "active",
    }
    try:
        res = client.table("drift_events").insert(row).execute()
        if res.data:
            event = res.data[0]
            event["parameter_label"] = PARAMETER_LABELS.get(parameter, parameter)
            return event
    except Exception as e:
        print(f"[detector] Drift event store failed: {e}")
    return None


def detect_drifts(client, junction_id: str, param_results: dict) -> list[dict]:
    """
    Full detection pass for all 9 parameters.

    Debouncing rules
    ----------------
    • If an active event already exists for this junction+parameter, we UPDATE
      it in-place (z_score / tier / confidence) and return it — no new row.
    • A new event is only inserted when there is no active event.
    • Resolution (in sentinel_main) uses RESOLVE_HYSTERESIS_Z so a T3 event
      won't close just because Z briefly dips from 3.1 to 2.9.
    """
    events = []
    for param, result in param_results.items():
        value   = result["value"]
        reason  = result["reason"]
        context = result.get("context", {})

        store_observation(client, junction_id, param, value, context)

        baseline = get_latest_baseline(client, junction_id, param)
        if not baseline:
            continue

        z          = compute_z_score(value, baseline)
        confidence = compute_confidence(z)
        tier       = assign_tier(z)

        # ── Check for an already-active event ───────────────────────────────
        active = get_active_event(client, junction_id, param)

        if tier >= 1:
            if active:
                # Drift is still ongoing — update the existing event in-place.
                update_drift_event(client, active["id"], z, confidence, tier, value)
                active.update({
                    "z_score":       round(z, 4),
                    "confidence":    confidence,
                    "tier":          tier,
                    "current_value": value,
                    "parameter_label": PARAMETER_LABELS.get(param, param),
                })
                events.append(active)
            else:
                # New drift onset — create a fresh event.
                event = store_drift_event(
                    client, junction_id, param,
                    value, baseline, z, confidence, tier, reason
                )
                if event:
                    events.append(event)
        # If tier == 0 and there is an active event, resolution is handled
        # separately in sentinel_main via check_and_resolve (with hysteresis).

    return events

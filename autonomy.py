"""
Tiered autonomy system.

Tier 1 — AI only:     Drift logged. AI continues. No human needed.
Tier 2 — Human + AI: AI flags the decision. Creates a pending review.
                      Human must approve or override before any action.
Tier 3 — SOS:         Critical drift. Automated control suspended.
                      Human must respond immediately.
"""
from datetime import datetime, timezone

TIER_LABELS = {
    1: "T1 — AI acknowledged",
    2: "T2 — Pending human review",
    3: "T3 — SOS: human required",
}

TIER_DESCRIPTIONS = {
    1: ("Drift detected and logged. AI is monitoring and will continue "
        "operating normally. No human action required."),
    2: ("Significant drift detected. AI has generated a recommended action "
        "but will NOT execute it until a human approves or overrides."),
    3: ("Critical drift. Automated traffic control for this junction is "
        "suspended. A human operator must review and intervene immediately."),
}


def _ai_decision_text(tier: int, junction_id: str, parameter: str,
                       z_score: float) -> str:
    if tier == 3:
        return (f"HALT: Suspend automated lane control for {junction_id}. "
                f"{parameter} has drifted {z_score:.2f}σ beyond baseline. "
                f"Manual override required before resuming automation.")
    if tier == 2:
        return (f"CAUTION: Reduce confidence weight for {junction_id}/{parameter}. "
                f"Z-score {z_score:.2f} indicates significant deviation. "
                f"Recommend human review of recent decisions.")
    return (f"MONITOR: Drift logged for {junction_id}/{parameter} "
            f"(z={z_score:.2f}). Continuing normal operation with increased logging.")


def handle_autonomy(client, event: dict, combo: dict | None = None) -> dict | None:
    tier       = event.get("tier", 1)
    junction   = event.get("junction_id", "")
    param      = event.get("parameter", "")
    z          = event.get("z_score", 0.0) or 0.0
    confidence = event.get("confidence", 0.0) or 0.0

    ai_decision = _ai_decision_text(tier, junction, param, z)
    notes       = TIER_DESCRIPTIONS[tier]
    if combo:
        notes += f"\n\nCombination alert active: {combo.get('reason', '')}"

    # Tier 1 is auto-acknowledged — no human needed
    status = "auto_acknowledged" if tier == 1 else "pending"

    row = {
        "event_id":      event.get("id"),
        "junction_id":   junction,
        "tier":          tier,
        "ai_decision":   ai_decision,
        "ai_confidence": confidence,
        "status":        status,
        "notes":         notes,
    }
    try:
        res = client.table("autonomy_log").insert(row).execute()
        if res.data:
            entry = res.data[0]
            entry["tier_label"] = TIER_LABELS[tier]
            return entry
    except Exception as e:
        print(f"[autonomy] Log failed: {e}")
    return None


def submit_human_decision(client, log_id: str, decision: str,
                           reviewer: str, notes: str = ""):
    """Human submits their decision on a Tier 2/3 event via the dashboard."""
    try:
        client.table("autonomy_log").update({
            "human_decision": decision,
            "human_reviewer": reviewer,
            "reviewed_at":    datetime.now(timezone.utc).isoformat(),
            "status":         "reviewed",
            "notes":          notes,
        }).eq("id", log_id).execute()
    except Exception as e:
        print(f"[autonomy] Human decision update failed: {e}")


def get_pending_reviews(client, limit: int = 50) -> list:
    try:
        return (
            client.table("autonomy_log")
            .select("*")
            .eq("status", "pending")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
            .data or []
        )
    except Exception as e:
        print(f"[autonomy] Pending fetch failed: {e}")
        return []

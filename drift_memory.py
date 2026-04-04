"""
Drift memory system.
Records onset, peak, and resolution snapshots for timeline replay.
Resolves active drift events when Z-score returns to normal.
"""
from datetime import datetime, timezone


def record_memory(client, event: dict, memory_type: str):
    """memory_type: 'onset' | 'peak' | 'resolution'"""
    snapshot = {
        "junction_id":   event.get("junction_id"),
        "parameter":     event.get("parameter"),
        "z_score":       event.get("z_score"),
        "confidence":    event.get("confidence"),
        "tier":          event.get("tier"),
        "current_value": event.get("current_value"),
        "baseline_mean": event.get("baseline_mean"),
        "reason":        event.get("reason"),
    }
    try:
        client.table("drift_memory").insert({
            "event_id":    event.get("id"),
            "junction_id": event.get("junction_id"),
            "parameter":   event.get("parameter"),
            "snapshot":    snapshot,
            "memory_type": memory_type,
        }).execute()
    except Exception as e:
        print(f"[drift_memory] Record failed ({memory_type}): {e}")


def get_timeline(client, junction_id: str, parameter: str = None,
                  limit: int = 500) -> list:
    try:
        q = (
            client.table("drift_memory")
            .select("*")
            .eq("junction_id", junction_id)
            .order("recorded_at", desc=False)
            .limit(limit)
        )
        if parameter:
            q = q.eq("parameter", parameter)
        return q.execute().data or []
    except Exception as e:
        print(f"[drift_memory] Timeline fetch failed: {e}")
        return []


def _resolve_event(client, event_id: str):
    try:
        client.table("drift_events").update({
            "status":      "resolved",
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", event_id).execute()
    except Exception as e:
        print(f"[drift_memory] Resolve failed: {e}")


def check_and_resolve(client, junction_id: str, parameter: str, current_tier: int):
    """
    If current tier has dropped back to 0 but there is an active event,
    record a resolution memory and close the event.
    """
    if current_tier > 0:
        return
    try:
        res = (
            client.table("drift_events")
            .select("*")
            .eq("junction_id", junction_id)
            .eq("parameter", parameter)
            .eq("status", "active")
            .order("detected_at", desc=True)
            .limit(1)
            .execute()
        )
        if res.data:
            event = res.data[0]
            record_memory(client, event, "resolution")
            _resolve_event(client, event["id"])
    except Exception as e:
        print(f"[drift_memory] Check-resolve failed: {e}")


def record_peak(client, junction_id: str, parameter: str, event: dict):
    """
    Update peak memory if the new Z-score exceeds the stored peak for this event.
    Called when the same parameter is still drifting on a subsequent tick.
    """
    try:
        existing = (
            client.table("drift_memory")
            .select("snapshot")
            .eq("event_id", event.get("id"))
            .eq("memory_type", "peak")
            .limit(1)
            .execute()
            .data
        )
        new_z = abs(event.get("z_score", 0) or 0)
        if not existing:
            record_memory(client, event, "peak")
        else:
            old_snap = existing[0].get("snapshot", {})
            old_z    = abs(old_snap.get("z_score", 0) or 0)
            if new_z > old_z:
                record_memory(client, event, "peak")
    except Exception as e:
        print(f"[drift_memory] Peak update failed: {e}")

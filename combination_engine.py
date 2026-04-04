"""
Detects multi-parameter drift combinations.
Rule: 3+ parameters drifting for the same junction in the same tick
      triggers a combination alert and escalates the tier by +1.
"""
COMBO_THRESHOLD = 3


def detect_combination(client, junction_id: str,
                         active_drifts: list[dict]) -> dict | None:
    if len(active_drifts) < COMBO_THRESHOLD:
        return None

    params        = [d["parameter"] for d in active_drifts]
    z_map         = {d["parameter"]: round(d["z_score"], 3) for d in active_drifts}
    max_tier      = max(d["tier"] for d in active_drifts)
    escalated     = min(max_tier + 1, 3)
    combined_score = round(
        sum(abs(z) for z in z_map.values()) / len(z_map), 3
    )

    parts  = [f"{p} (z={z_map[p]:.2f})" for p in params]
    reason = (f"{len(params)}-parameter simultaneous drift: "
              f"{', '.join(parts)}. "
              f"Escalated from Tier {max_tier} to Tier {escalated}.")

    combo = {
        "junction_id":          junction_id,
        "parameters":           params,
        "individual_z_scores":  z_map,
        "combined_score":       combined_score,
        "escalated_tier":       escalated,
        "reason":               reason,
        "status":               "active",
    }
    try:
        res = client.table("combination_alerts").insert(combo).execute()
        if res.data:
            return res.data[0]
    except Exception as e:
        print(f"[combo] Store failed: {e}")
    return None

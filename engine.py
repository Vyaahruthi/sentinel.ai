from metrics import *
from alerts import confidence
from db import client

def fetch_decisions(junction_id, limit=200):
    res = client.table("decisions")\
        .select("*")\
        .eq("junction_id", junction_id)\
        .order("timestamp", desc=True)\
        .limit(limit)\
        .execute()
    return res.data


def get_tier(score, all_scores):
    if not all_scores:
        return "Tier 1 (AI)"

    mean = sum(all_scores) / len(all_scores)

    # ✅ safer std calculation
    variance = sum([(s - mean) ** 2 for s in all_scores]) / len(all_scores)
    std = variance ** 0.5 if variance > 0 else 0.1  # 🔥 fix: avoid zero std

    if score <= mean:
        return "Tier 1 (AI)"
    elif score <= mean + std:
        return "Tier 2 (Human+AI)"
    else:
        return "Tier 3 (SOS)"


def process_junction(junction):
    data = fetch_decisions(junction)

    if not data:
        return []

    traffic = [d["original_traffic"] for d in data if d.get("original_traffic") is not None]
    lanes = [d["lanes_allocated"] for d in data if d.get("lanes_allocated") is not None]

    if not traffic or not lanes:
        return []

    results = []
    scores = []

    # ✅ FIX: detect incident properly (not always False)
    incident = any(d.get("has_incident", False) for d in data)

    functions = [
        ("Behaviour Adaptation", lambda: behaviour_adaptation(lanes)),
        ("Data Bias", lambda: data_bias(lanes)),
        ("Data Drift", lambda: data_drift(traffic)),
        ("Feedback Loop", lambda: feedback_loop(lanes, traffic)),
        ("Silent Drift", lambda: silent_drift(traffic)),
        ("Infrastructure Change", lambda: infra_change(traffic)),
        ("Policy Change", lambda: policy_change(traffic, lanes)),
        ("Technology Influence", lambda: tech_influence(traffic)),
        ("Event Traffic", lambda: event_traffic(traffic, incident))  # ✅ FIXED
    ]

    for name, func in functions:
        try:
            score, z, reason = func()

            # ✅ safety fixes
            z = float(max(min(z, 10), -10))   # clamp extreme values
            score = float(score)

            conf = float(confidence(z))

        except Exception as e:
            print(f"[engine] Error in {name}: {e}")
            score, z, conf = 0.0, 0.0, 0.0
            reason = "Computation error"

        scores.append(score)

        results.append({
            "junction_id": junction,
            "parameter": name,
            "score": score,
            "z_score": z,
            "confidence": conf,
            "reason": reason,
            "current_value": float(traffic[0]) if traffic else 0.0
        })

    # ✅ tier assignment AFTER all scores computed
    for r in results:
        r["tier"] = get_tier(r["score"], scores)

    return results

    
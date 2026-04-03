import statistics
from simulator import JUNCTIONS

def fetch_baseline(client, junction_id, limit=200):
    """Fetches the most recent `limit` rows to compute baseline standard deviation and mean."""
    response = client.table("traffic_logs").select("*").eq("junction_id", junction_id).order("timestamp", desc=True).limit(limit).execute()
    return response.data

def compute_decision(record, client):
    """Computes lane allocation decision based on recent traffic history and current conditions."""
    junction_id = record["junction_id"]
    baseline_records = fetch_baseline(client, junction_id, limit=200)
    
    if len(baseline_records) < 30:
        return {
            "junction_id": junction_id,
            "timestamp": record["timestamp"],
            "original_traffic": record["traffic_volume"],
            "z_score": 0.0,
            "lanes_allocated": 1,
            "reason": "Cold-start: not enough history (min 30 rows)"
        }
        
    volumes = [r["traffic_volume"] for r in baseline_records]
    mean_vol = statistics.mean(volumes)
    std_vol = statistics.stdev(volumes) if len(volumes) > 1 else 0.0
    std_vol = max(std_vol, 1.0) # Protect std
    
    current_vol = record["traffic_volume"]
    z_score = (current_vol - mean_vol) / std_vol
    
    # Base lane allocation from Z-score
    if z_score < 1:
        lanes = 1
    elif 1 <= z_score < 2:
        lanes = 2
    else:
        lanes = 3
        
    j_props = JUNCTIONS[junction_id]
    j_type = j_props["type"]
    capacity = j_props["capacity"]
    
    utilisation = current_vol / capacity if capacity > 0 else 0
    
    reasons = [f"Base lanes for Z-score {z_score:.2f} (mean: {mean_vol:.1f}, std: {std_vol:.1f}): {lanes}"]
    
    # Context rules
    if record["has_incident"]:
        lanes = min(3, lanes + 1)
        reasons.append("Incident: added 1 lane (capped at 3)")
        
    if utilisation > 0.9:
        if lanes < 3:
            lanes = 3
            reasons.append(f"Utilisation >90% ({utilisation*100:.1f}%): forced 3 lanes")
    elif utilisation < 0.3:
        # Before reducing to 1, make sure we aren't overriding mandatory rules
        # e.g., highway enforces min 2, peak/event enforces min 2
        pass # Handle this dynamically by allowing it first, then capping minimums
        lanes = 1
        reasons.append(f"Utilisation <30% ({utilisation*100:.1f}%): reduced to 1 lane")
        
    # Minimum enforcement rules (overrides any reductions)
    if j_type == "highway" and lanes < 2:
        lanes = 2
        reasons.append("Highway rule: enforce minimum 2 lanes")
        
    if (record["is_peak_hour"] or record["is_event"]) and lanes < 2:
        lanes = 2
        reasons.append("Peak/Event active: enforce minimum 2 lanes")
        
    decision = {
        "junction_id": junction_id,
        "timestamp": record["timestamp"],
        "original_traffic": current_vol,
        "z_score": z_score,
        "lanes_allocated": lanes,
        "reason": " | ".join(reasons)
    }
    return decision

import random
from datetime import datetime, timezone

JUNCTIONS = {
    "J1": {"type": "highway", "capacity": 400, "base": 200},
    "J2": {"type": "intersection", "capacity": 200, "base": 100},
    "J3": {"type": "roundabout", "capacity": 150, "base": 75}
}

def generate_tick():
    """Generates a traffic tick for all junctions."""
    tick_data = []
    now = datetime.now(timezone.utc).isoformat()
    for j_id, props in JUNCTIONS.items():
        base = props["base"]
        noise = random.randint(-30, 30)
        
        is_peak = random.random() < 0.15
        is_event = random.random() < 0.08
        has_incident = random.random() < 0.05
        
        surge = 0
        if is_peak or is_event:
            surge = random.randint(50, 120)
            
        spike = 0
        if has_incident:
            spike = random.randint(80, 160)
            
        traffic_volume = max(0, base + noise + surge + spike)
        
        tick_data.append({
            "junction_id": j_id,
            "timestamp": now,
            "traffic_volume": traffic_volume,
            "is_peak_hour": is_peak,
            "is_event": is_event,
            "has_incident": has_incident
        })
    return tick_data

def log_tick(client, tick_data):
    """Inserts tick data into traffic_logs and returns the inserted records."""
    response = client.table("traffic_logs").insert(tick_data).execute()
    return response.data

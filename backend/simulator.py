import sys
import time
import random
from datetime import datetime, timezone
import os

# Append the project root to sys.path so it can find the backend module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import supabase

JUNCTIONS = {
    "J1": {"type": "highway", "capacity": 400, "base": 200},
    "J2": {"type": "intersection", "capacity": 200, "base": 100},
    "J3": {"type": "roundabout", "capacity": 150, "base": 75}
}

def generate_tick():
    """Generates a Sentinel-compatible traffic tick for all 3 junctions natively."""
    now = datetime.now(timezone.utc).isoformat()
    ticks = []
    
    for j_id, props in JUNCTIONS.items():
        base = props["base"]
        noise = random.randint(int(-base*0.1), int(base*0.1))
        
        is_peak = random.random() < 0.15
        is_event = random.random() < 0.08
        has_incident = random.random() < 0.05
        
        surge = random.randint(int(base*0.2), int(base*0.4)) if is_peak else 0
        spike = random.randint(int(base*0.3), int(base*0.6)) if has_incident else 0
        event_surge = random.randint(int(base*0.2), int(base*0.5)) if is_event else 0
        
        traffic_volume = max(10, base + noise + surge + spike + event_surge)
        
        # This matches EXACTLY the traffic_logs postgres schema!
        tick_data = {
            "junction_id": j_id,
            "timestamp": now,
            "traffic_volume": traffic_volume,
            "is_peak_hour": is_peak,
            "is_event": is_event,
            "has_incident": has_incident
        }
        ticks.append(tick_data)
        
    return ticks

def log_tick(client, tick_data):
    """Inserts tick data into logs and returns the inserted records."""
    try:
        response = client.table("traffic_logs").insert(tick_data).execute()
        return response.data
    except Exception as e:
        print(f"Error inserting log: {e}")
        return None

if __name__ == "__main__":
    print("🚦 Starting Sentinel Base Simulator...")
    run_count = 0
    while True:
        try:
            ticks = generate_tick()
            for tick in ticks:
                log_tick(supabase, tick)
            run_count += 1
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Tick {run_count:04d} | Simulated {len(ticks)} junctions.")
            
            # Ping every 3 seconds to generate realistic time-series
            time.sleep(3)
        except KeyboardInterrupt:
            print("\n🛑 Simulator stopped.")
            break
        except Exception as e:
            print(f"Simulation Error: {e}")
            time.sleep(5)

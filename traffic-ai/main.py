import time
from db import get_db_client
from simulator import generate_tick, log_tick
from engine import compute_decision

def run():
    client = get_db_client()
    print("Starting Traffic AI Simulator...")
    
    while True:
        try:
            tick_data = generate_tick()
            logged_records = log_tick(client, tick_data)
            
            decisions = []
            for record in logged_records:
                decision = compute_decision(record, client)
                decisions.append(decision)
                
            client.table("decisions").insert(decisions).execute()
            
            for d in decisions:
                z_str = f"{d['z_score']:.2f}"
                print(f"[{d['timestamp']}] {d['junction_id']} | Traffic: {d['original_traffic']:>3} | Z: {z_str:>5} | Lanes: {d['lanes_allocated']} | {d['reason']}")
                
        except Exception as e:
            print(f"Error in tick log/compute: {e}")
            
        time.sleep(2)

if __name__ == "__main__":
    run()



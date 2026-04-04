import time
from engine import process_junction
from db import client
from drift_detector import detect_drifts

junctions = ["J1", "J2", "J3"]

def run():
    print("🚀 Starting Sentinel-AI daemon...")

    while True:
        try:
            for j in junctions:
                print(f"\n🔄 Processing {j}...")

                results = process_junction(j)

                # ❌ No data from engine
                if not results:
                    print(f"⚠️ {j}: No data received from engine")
                    continue

                print(f"✅ {j}: {len(results)} parameters computed")

                # ✅ Convert engine output → detector input
                param_map = {
                    r["parameter"].lower().replace(" ", "_"): {
                        "value": r["score"],
                        "reason": r["reason"]
                    }
                    for r in results
                }

                # ✅ Run drift detection (handles DB insert properly)
                events = detect_drifts(client, j, param_map)

                if events:
                    print(f"🚨 {j}: {len(events)} drift events detected")
                else:
                    print(f"🟢 {j}: No significant drift")

        except Exception as e:
            print(f"❌ Error processing junction: {e}")

        time.sleep(5)


if __name__ == "__main__":
    run()
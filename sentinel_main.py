"""
Main sentinel loop. Runs every 5 seconds.
Reads from traffic-ai tables, computes all 9 parameters,
detects drifts, manages memory, combinations, and autonomy tiers.
"""
import time
from sentinel_db import get_client
from parameters import compute_all_parameters, PARAMETER_NAMES
from baseline_engine import (
    compute_and_store_baseline, get_latest_baseline, compute_z_score
)
from drift_detector import detect_drifts, assign_tier
from drift_memory import record_memory, check_and_resolve, record_peak
from combination_engine import detect_combination
from autonomy import handle_autonomy

JUNCTIONS            = ["J1", "J2", "J3"]
SENTINEL_INTERVAL    = 5   # seconds per scan
BASELINE_RECOMPUTE_N = 12  # recompute baseline every 12 ticks (~60 seconds)

tick = 0


def run():
    global tick
    client = get_client()
    print("Sentinel.AI monitoring started.\n")

    while True:
        tick += 1
        print(f"\n{'='*50}")
        print(f"Sentinel tick #{tick}")
        print(f"{'='*50}")

        for junction_id in JUNCTIONS:
            print(f"\n  [{junction_id}]")

            # Step 1: Compute all 9 parameter values from traffic-ai data
            params = compute_all_parameters(client, junction_id)

            # Step 2: Recompute baselines every BASELINE_RECOMPUTE_N ticks
            if tick % BASELINE_RECOMPUTE_N == 1:
                for param in PARAMETER_NAMES:
                    compute_and_store_baseline(client, junction_id, param)
                print("    Baselines refreshed.")

            # Step 3: Detect drifts — stores observations + drift events
            active_drifts = detect_drifts(client, junction_id, params)

            # Step 4: Record onset memory and handle autonomy per drift
            combo = None
            if len(active_drifts) >= 3:
                combo = detect_combination(client, junction_id, active_drifts)
                if combo:
                    print(f"    COMBINATION ALERT: {len(active_drifts)} params "
                          f"→ escalated Tier {combo['escalated_tier']}")

            for event in active_drifts:
                record_memory(client, event, "onset")
                record_peak(client, junction_id, event["parameter"], event)
                handle_autonomy(client, event, combo)

                tier_str = {1: "T1·AI", 2: "T2·REVIEW", 3: "T3·SOS"}.get(
                    event["tier"], "?"
                )
                print(
                    f"    [{tier_str}] {event.get('parameter'):<24} "
                    f"z={event.get('z_score'):+.2f}  "
                    f"conf={event.get('confidence'):.0f}%  "
                    f"| {str(event.get('reason',''))[:55]}"
                )

            # Step 5: Check for resolved drifts (tier dropped back to 0)
            for param in PARAMETER_NAMES:
                value    = params.get(param, {}).get("value", 0)
                baseline = get_latest_baseline(client, junction_id, param)
                if baseline:
                    z    = compute_z_score(value, baseline)
                    tier = assign_tier(z)
                    check_and_resolve(client, junction_id, param, tier)

            if not active_drifts:
                print("    All 9 parameters within normal range.")

        time.sleep(SENTINEL_INTERVAL)


if __name__ == "__main__":
    run()

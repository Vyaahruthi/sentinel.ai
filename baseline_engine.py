"""
Dynamic baseline management.
Baselines are computed from sentinel_observations and stored in sentinel_baselines.
Z-score and confidence are computed fresh from the latest stored baseline.
"""
import math
import pandas as pd

BASELINE_MIN_SAMPLES = 20
BASELINE_WINDOW      = 200


def fetch_observations(client, junction_id: str, parameter: str,
                        limit: int = BASELINE_WINDOW) -> pd.DataFrame:
    try:
        res = (
            client.table("sentinel_observations")
            .select("value, timestamp")
            .eq("junction_id", junction_id)
            .eq("parameter", parameter)
            .order("timestamp", desc=True)
            .limit(limit)
            .execute()
        )
        df = pd.DataFrame(res.data or [])
        if not df.empty:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df
    except Exception as e:
        print(f"[baseline] Fetch obs failed {junction_id}/{parameter}: {e}")
        return pd.DataFrame()


def compute_and_store_baseline(client, junction_id: str, parameter: str) -> dict | None:
    df = fetch_observations(client, junction_id, parameter)
    if len(df) < BASELINE_MIN_SAMPLES:
        return None
    mean = float(df["value"].mean())
    std  = float(max(df["value"].std(), 1e-9))
    bl = {
        "junction_id":  junction_id,
        "parameter":    parameter,
        "mean":         round(mean, 9),
        "std":          round(std, 9),
        "sample_size":  len(df),
        "window_start": df["timestamp"].min().isoformat(),
        "window_end":   df["timestamp"].max().isoformat(),
    }
    try:
        client.table("sentinel_baselines").insert(bl).execute()
    except Exception as e:
        print(f"[baseline] Store failed: {e}")
    return bl


def get_latest_baseline(client, junction_id: str, parameter: str) -> dict | None:
    try:
        res = (
            client.table("sentinel_baselines")
            .select("*")
            .eq("junction_id", junction_id)
            .eq("parameter", parameter)
            .order("computed_at", desc=True)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]
    except Exception as e:
        print(f"[baseline] Get failed: {e}")
    return None


def compute_z_score(value: float, baseline: dict) -> float:
    std = max(baseline["std"], 1e-9)
    return (value - baseline["mean"]) / std


def compute_confidence(z_score: float) -> float:
    """Sigmoid-style mapping. z=1.5→~45%, z=2.5→~63%, z=3.5→~75%, z=5→~87%"""
    conf = 100 * (1 - math.exp(-0.35 * abs(z_score)))
    return round(min(conf, 99.5), 1)

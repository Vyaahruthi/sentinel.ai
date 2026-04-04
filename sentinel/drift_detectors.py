import pandas as pd
import numpy as np
from scipy.stats import linregress

def detect_drifts(df: pd.DataFrame) -> dict:
    """
    Implements 9 behaviour-drift detectors based on traffic engineering principles.
    Expects a DataFrame with the latest 500 logs.
    """
    metrics = {
        "behaviour_adaptation": 0.0,
        "data_bias": 0.0,
        "data_drift": 0.0,
        "feedback_loop": 0.0,
        "silent_drift": 0.0,
        "infrastructure_change": 0.0,
        "policy_change": 0.0,
        "technology_influence": 0.0,
        "event_traffic": 0.0
    }
    
    if df.empty or len(df) < 50:
        return metrics
        
    # Sort by time to ensure chronological order
    df = df.sort_values("event_time").reset_index(drop=True)
    x = np.arange(len(df))
    
    try:
        # 1. Behaviour adaptation: Drivers learning shortcuts -> regression slope of congestion
        slope, _, _, _, _ = linregress(x, df['congestion_index'])
        metrics["behaviour_adaptation"] = float(slope)
        
        # 2. Data bias: weekday vs weekend. We'll simulate this by looking at variance in traffic across hour types
        # Since simulation runs fast, we simply use the difference between the top 20% and bottom 20% traffic means
        top_20 = df['traffic'].quantile(0.8)
        bottom_20 = df['traffic'].quantile(0.2)
        metrics["data_bias"] = float((top_20 - bottom_20) / df['traffic'].mean() if df['traffic'].mean() > 0 else 0)
        
        # 3. Data drift: μ_recent - μ_historical
        mid = len(df) // 2
        historical_mean = df['traffic'].iloc[:mid].mean()
        recent_mean = df['traffic'].iloc[mid:].mean()
        metrics["data_drift"] = float(abs(recent_mean - historical_mean))
        
        # 4. Feedback loops: Signal decisions influencing driver routes -> corr(traffic, active_lanes)
        corr = df['traffic'].corr(df['active_lanes'])
        metrics["feedback_loop"] = float(corr) if not pd.isna(corr) else 0.0
        
        # 5. Silent drift: Slow behavioural change -> Use regression trend on traffic
        slope_traffic, _, _, _, _ = linregress(x, df['traffic'])
        metrics["silent_drift"] = float(slope_traffic)
        
        # 6. Infrastructure change: Traffic shifts between junction types
        jtypes = df['junction_type'].value_counts(normalize=True)
        # We calculate variance of the distribution as a proxy
        metrics["infrastructure_change"] = float(jtypes.var() * 100) if not pd.isna(jtypes.var()) else 0.0
        
        # 7. Policy change: Traffic behaviour before vs after policy change
        # Simulated by absolute difference in congestion index
        cong_hist = df['congestion_index'].iloc[:mid].mean()
        cong_rec = df['congestion_index'].iloc[mid:].mean()
        metrics["policy_change"] = float(abs(cong_rec - cong_hist))
        
        # 8. Technology influence: Navigation apps causing route spikes -> traffic spike without incident
        spikes = df[(df['traffic'] > df['traffic'].mean() * 1.5) & (df['incident'] == False)]
        metrics["technology_influence"] = float(len(spikes))
        
        # 9. Event-driven traffic: incident frequency
        metrics["event_traffic"] = float(df['incident'].sum())
        
    except Exception as e:
        print(f"Error calculating drift metrics: {e}")
        
    return metrics

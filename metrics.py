import numpy as np
from baseline import compute_baseline, z_score, normalize

def data_drift(traffic):
    if not traffic:
        return 0, 0, "No traffic data"
    mean, std = compute_baseline(traffic)
    z = z_score(traffic[0], mean, std)
    return normalize(z), z, "Traffic deviated from baseline"


def behaviour_adaptation(lanes):
    if len(lanes) < 51:
        return 0, 0, "Insufficient data for behavior adaptation"
    recent = lanes[:50]
    past = lanes[50:]

    m1, _ = compute_baseline(recent)
    m2, s2 = compute_baseline(past)

    z = z_score(m1, m2, s2)
    return normalize(z), z, "Decision pattern changed"


def data_bias(lanes):
    if not lanes:
        return 0, 0, "No lane data"
    mean, std = compute_baseline(lanes)
    z = z_score(lanes[0], mean, std)
    return normalize(z), z, "Bias in lane allocation"


def feedback_loop(lanes, traffic):
    if len(lanes) < 10 or len(traffic) < 10:
        return 0, 0, "Insufficient data"

    # Avoid numpy warnings for identical arrays
    std_lanes = np.std(lanes[:-1])
    std_traffic = np.std(traffic[1:])
    
    if std_lanes == 0 or std_traffic == 0:
        return 0, 0, "Flat variance, no feedback loop detected"

    corr = np.corrcoef(lanes[:-1], traffic[1:])[0][1]
    if np.isnan(corr):
        corr = 0
    z = corr / 0.3
    return normalize(z), z, "Feedback loop detected"


def silent_drift(values):
    if len(values) < 2:
        return 0, 0, "Insufficient data for silent drift"
    trend = np.polyfit(range(len(values)), values, 1)[0]
    std = np.std(values)
    z = trend / (std if std != 0 else 1)
    return normalize(z), z, "Gradual drift detected"


def infra_change(traffic):
    if not traffic:
        return 0, 0, "No traffic data"
    mean, std = compute_baseline(traffic)
    z = z_score(traffic[0], mean, std)
    return normalize(z), z, "Infrastructure mismatch"


def policy_change(traffic, lanes):
    if len(lanes) < 2:
        return 0, 0, "Insufficient data for policy change"
    diff = [abs(lanes[i]-lanes[i-1]) for i in range(1,len(lanes))]
    mean, std = compute_baseline(diff)
    z = z_score(diff[0], mean, std)
    return normalize(z), z, "Policy inconsistency"


def tech_influence(traffic):
    if not traffic:
        return 0, 0, "No data"
    mean, std = compute_baseline(traffic)
    z = z_score(traffic[0], mean, std)
    return normalize(z), z, "External influence spike"


def event_traffic(traffic, incident):
    if not incident:
        return 0, 0, "No event"
    if not traffic:
        return 0, 0, "No traffic data"
    mean, std = compute_baseline(traffic)
    z = z_score(traffic[0], mean, std)
    return normalize(z), z, "Event-driven surge"

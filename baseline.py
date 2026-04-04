import numpy as np

MIN_STD = 0.1  # prevents z-score explosion (tunable)

def compute_baseline(values):
    if not values:
        return 0, 1

    mean = np.mean(values)
    std = np.std(values)

    # ✅ fix: avoid tiny std (main issue)
    std = max(std, MIN_STD)

    return mean, std


def z_score(current, mean, std):
    std = max(std, MIN_STD)  # ✅ ensure safe division
    z = (current - mean) / std

    # ✅ optional: clamp extreme values (important for UI)
    z = max(min(z, 10), -10)

    return z


def normalize(z):
    # ✅ better scaling (smooth + bounded)
    return min(abs(z) / 3, 1)
    

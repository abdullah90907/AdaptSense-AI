"""Fixed-lead replay assessment with period-level descriptive uncertainty."""
import numpy as np


def period_metrics(origins):
    rows = [row for origin in origins for row in origin["evidence"]]
    errors = np.array([r["absolute_error"] for r in rows])
    naive = float(np.mean([r["baseline_absolute_error"] for r in rows]))
    mae = float(errors.mean())
    return {"start": rows[0]["timestamp"], "end": rows[-1]["timestamp"],
            "origins": len(origins), "observations": len(rows), "mae": mae,
            "rmse": float(np.sqrt(np.mean(errors ** 2))), "baseline_mae": naive,
            "skill_vs_baseline": 1 - mae / naive if naive > 1e-9 else None,
            "q10_q90_coverage": float(np.mean([r["covered"] for r in rows]))}


def assess(origins, period_origins, reference_scale):
    reference, recent = origins[:period_origins], origins[period_origins:]
    a = np.array([o["mae"] for o in reference])
    b = np.array([o["mae"] for o in recent])
    threshold = max(0.2 * float(a.mean()), 0.1 * reference_scale, 1e-9)
    rng = np.random.default_rng(20261026)
    block_length = 3

    def resample(values):
        starts = rng.integers(0, len(values), size=(2000, (len(values) + block_length - 1) // block_length))
        indices = (starts[..., None] + np.arange(block_length)) % len(values)
        return values[indices.reshape(2000, -1)[:, :len(values)]].mean(axis=1)

    changes = resample(b) - resample(a)
    lower, upper = [float(x) for x in np.quantile(changes, [0.025, 0.975])]
    delta = float(b.mean() - a.mean())
    split = len(b) // 2
    halves = [float(b[:split].mean()), float(b[split:].mean())]
    sustained = all(x > float(a.mean()) + threshold for x in halves)
    status = "deterioration_supported" if lower > threshold and sustained else (
        "possible_deterioration" if delta > threshold else "no_deterioration_detected")
    leads = []
    for lead in range(len(origins[0]["evidence"])):
        before = float(np.mean([o["evidence"][lead]["absolute_error"] for o in reference]))
        after = float(np.mean([o["evidence"][lead]["absolute_error"] for o in recent]))
        leads.append({"lead": lead + 1, "reference_mae": before, "recent_mae": after, "delta_mae": after - before})
    return {"status": status, "reference": period_metrics(reference), "recent": period_metrics(recent),
            "delta_mae": delta, "practical_delta_threshold": threshold,
            "reference_history_scale": reference_scale, "recent_half_maes": halves,
            "sustained": sustained, "delta_mae_bootstrap_interval": [lower, upper],
            "uncertainty": {"method": "independent circular moving-block bootstrap within each period",
                            "block_length_origins": block_length, "resamples": 2000,
                            "seed": 20261026, "interval_level": 0.95,
                            "interpretation": "Descriptive uncertainty under within-period weak stationarity; not a calibrated drift probability or sequential alarm."},
            "per_lead": leads,
            "decision_rule": "Supported only when lower interval bound exceeds max(20% reference MAE, 10% pre-reference seasonal-difference scale, 1e-9) and both recent halves exceed reference MAE by that threshold."}

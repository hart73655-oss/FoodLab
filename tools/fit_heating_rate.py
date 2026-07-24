"""
tools/fit_heating_rate.py
FoodLab v0.1.5

Fits the heating_rate parameter in mixture_heating.py
to observed time-temperature data from kitchen experiments.

Supports:
  - Constant or measured pan-temperature mode
  - Multiple replicates with separate fits
  - Replicate-level bootstrap (preserves temporal structure)
  - Row-level bootstrap fallback for single replicates
  - Calibration / validation split
  - Two-stage grid search for precision
  - Residual diagnostics with trend detection
  - Strict input validation
  - Shared heating model from models/mixture_heating.py
  - Heuristic structural adequacy comparison (not a formal F-test)
  - Parameter-uncertainty interval (k uncertainty only)
  - Experiment fingerprinting via SHA-256
  - Versioned calibration artifact with latest.json pointer
  - ASCII temperature curve visualization

Scientific honesty notes:
  - The structural adequacy test is a heuristic SSE comparison.
    It is NOT a formal statistical F-test.
    It does not compute p-values or assume a specific error distribution.

  - Predictive intervals capture only parameter uncertainty in k.
    They do NOT include thermometer error, pan-temperature
    uncertainty, process variability, or structural model error.

  - Bootstrap uses replicate-level resampling when multiple
    replicates are available, preserving temporal structure.
    Row-level resampling is a documented fallback for one replicate.

  - This tool imports models.mixture_heating.estimate_food_temperature
    directly, ensuring calibration and simulation use identical code.

Usage:
    python tools/fit_heating_rate.py --help

    Single replicate:
        python tools/fit_heating_rate.py \\
            --data experiments/EXP-0001-R1/temperatures.csv \\
            --experiment-id EXP-0001-R1

    Three replicates with validation and bootstrap:
        python tools/fit_heating_rate.py \\
            --data experiments/EXP-0001-R1/temperatures.csv \\
                   experiments/EXP-0001-R2/temperatures.csv \\
                   experiments/EXP-0001-R3/temperatures.csv \\
            --validation-replicate 3 \\
            --bootstrap 1000 \\
            --experiment-id EXP-0001 \\
            --save-residuals results/EXP-0001-residuals.csv

Run from foodlab/ root.
"""

import argparse
import csv
import hashlib
import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Project root
# ---------------------------------------------------------------------------

PROJECT_ROOT    = Path(__file__).resolve().parent.parent
CALIBRATION_DIR = PROJECT_ROOT / "calibration"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from models.mixture_heating import estimate_food_temperature     # noqa: E402


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERSION      = "0.1.5"
QUALITY_NOTE = "heuristic — not an objective verdict"


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"FoodLab — Heating Rate Calibration Tool v{VERSION}",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--data",
        type=str,
        nargs="+",
        default=None,
        help=(
            "One or more CSV files, one per replicate. "
            "Required columns: time_sec, food_temp_c. "
            "Optional column: pan_temp_c, notes."
        ),
    )
    parser.add_argument(
        "--pan",
        type=float,
        default=150.0,
        help=(
            "Constant pan temperature in Celsius. "
            "Used as fallback when pan_temp_c is absent from CSV."
        ),
    )
    parser.add_argument(
        "--initial-temp",
        type=float,
        default=20.0,
        help="Initial food temperature in Celsius.",
    )
    parser.add_argument(
        "--thermometer-accuracy",
        type=float,
        default=1.0,
        help="Thermometer accuracy ±°C. Used to contextualise quality labels.",
    )
    parser.add_argument(
        "--low",
        type=float,
        default=0.0001,
        help="Lower search bound for heating_rate (1/second).",
    )
    parser.add_argument(
        "--high",
        type=float,
        default=0.1,
        help="Upper search bound for heating_rate (1/second).",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=1000,
        help="Coarse grid points for stage-1 search.",
    )
    parser.add_argument(
        "--refine-steps",
        type=int,
        default=10000,
        help="Fine grid points for stage-2 search.",
    )
    parser.add_argument(
        "--validation-replicate",
        type=int,
        default=None,
        help="1-based index of replicate to hold out for validation.",
    )
    parser.add_argument(
        "--bootstrap",
        type=int,
        default=0,
        help=(
            "Bootstrap iterations for confidence interval. "
            "0 disables. "
            "Uses replicate-level resampling when >1 replicate."
        ),
    )
    parser.add_argument(
        "--bootstrap-seed",
        type=int,
        default=42,
        help="Random seed for reproducible bootstrap.",
    )
    parser.add_argument(
        "--experiment-id",
        type=str,
        default="EXP-UNKNOWN",
        help="Experiment ID recorded in calibration artifact.",
    )
    parser.add_argument(
        "--save-residuals",
        type=str,
        default=None,
        help="Optional path to save residual CSV.",
    )
    parser.add_argument(
        "--no-artifact",
        action="store_true",
        help="Skip saving calibration artifact to calibration/heating_rate/.",
    )
    parser.add_argument(
        "--no-plot",
        action="store_true",
        help="Skip ASCII temperature curve.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------

def fingerprint_files(filepaths: list[str]) -> str:
    """
    Computes SHA-256 hash of all input CSV files combined.
    Links calibration results to exact source data for provenance.
    Sorted by path so order of --data arguments does not affect hash.
    """
    h = hashlib.sha256()
    for filepath in sorted(filepaths):
        path = Path(filepath)
        if path.exists():
            h.update(path.read_bytes())
    return h.hexdigest()[:16]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_replicate(
    filepath: str,
    initial_temp_c: float,
    constant_pan_temp_c: float,
) -> list[dict]:
    """
    Loads one CSV replicate.

    Required columns: time_sec, food_temp_c
    Optional columns: pan_temp_c, notes

    Rows with non-numeric time_sec or food_temp_c are skipped
    with a warning. Missing pan_temp_c falls back to constant_pan_temp_c.

    Returns list of dicts:
        time_sec    float
        food_temp_c float
        pan_temp_c  float
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    rows = []
    with path.open("r", encoding="utf-8") as f:
        reader     = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or [])

        if "time_sec" not in fieldnames:
            raise ValueError(f"{filepath}: missing required column 'time_sec'.")
        if "food_temp_c" not in fieldnames:
            raise ValueError(f"{filepath}: missing required column 'food_temp_c'.")

        has_pan_col = "pan_temp_c" in fieldnames

        for i, row in enumerate(reader, start=2):
            try:
                time_sec    = float(row["time_sec"])
                food_temp_c = float(row["food_temp_c"])
            except (ValueError, KeyError):
                print(
                    f"  WARNING: {filepath} row {i} skipped "
                    f"— non-numeric value: {dict(row)}"
                )
                continue

            try:
                raw_pan = row.get("pan_temp_c", "").strip()
                pan_temp_c = (
                    float(raw_pan)
                    if has_pan_col and raw_pan
                    else constant_pan_temp_c
                )
            except ValueError:
                pan_temp_c = constant_pan_temp_c

            rows.append({
                "time_sec":    time_sec,
                "food_temp_c": food_temp_c,
                "pan_temp_c":  pan_temp_c,
            })

    return rows


# ---------------------------------------------------------------------------
# Data validation
# ---------------------------------------------------------------------------

def validate_replicate(
    rows: list[dict],
    initial_temp_c: float,
    label: str,
) -> list[str]:
    """
    Validates one replicate.
    Returns list of warning strings.
    Does not raise — caller decides whether to abort.
    """
    warnings = []
    n        = len(rows)

    if n < 3:
        warnings.append(
            f"{label}: fewer than 3 valid observations ({n}). "
            "Fit will be unreliable."
        )

    if n == 0:
        return warnings

    times = [r["time_sec"]    for r in rows]
    temps = [r["food_temp_c"] for r in rows]

    if any(t < 0 for t in times):
        warnings.append(f"{label}: negative timestamps detected.")

    if times != sorted(times):
        warnings.append(f"{label}: timestamps are not in ascending order.")

    if len(set(times)) != len(times):
        warnings.append(f"{label}: duplicate timestamps detected.")

    if any(not math.isfinite(t) for t in temps):
        warnings.append(f"{label}: non-finite food temperatures (NaN or inf).")

    if any(temp > 200 for temp in temps):
        warnings.append(
            f"{label}: food temperature exceeds 200°C. "
            "Check for measurement errors."
        )

    if abs(rows[0]["food_temp_c"] - initial_temp_c) > 5.0:
        warnings.append(
            f"{label}: first observation ({rows[0]['food_temp_c']}°C) "
            f"differs from --initial-temp ({initial_temp_c}°C) by more than 5°C. "
            "Check that timing started at t=0 when food was added."
        )

    return warnings


# ---------------------------------------------------------------------------
# Prediction — uses engine's own function
# ---------------------------------------------------------------------------

def predict_sequence(
    rows: list[dict],
    heating_rate: float,
    initial_temp_c: float,
) -> list[float]:
    """
    Predicts food temperature for each row using the engine's
    estimate_food_temperature function.

    Per-row pan_temp_c is used when available, making this
    compatible with measured-pan-temperature experiments.

    Calibration and simulation use identical code paths.
    """
    return [
        estimate_food_temperature(
            initial_temp_c=initial_temp_c,
            pan_temp_c=row["pan_temp_c"],
            elapsed_sec=row["time_sec"],
            heating_rate=heating_rate,
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Error metrics
# ---------------------------------------------------------------------------

def compute_metrics(
    rows: list[dict],
    heating_rate: float,
    initial_temp_c: float,
) -> dict:
    """
    Computes SSE, RMSE, MAE, mean error, max absolute error,
    and linear residual slope.

    RMSE and MAE are in Celsius for physical interpretability.

    Residual slope (°C/s):
        Positive = model underestimates at late times.
        Negative = model overestimates at late times.
        Near zero = no systematic time trend.
    """
    predictions = predict_sequence(rows, heating_rate, initial_temp_c)
    n           = len(rows)

    sse = sum_ae = sum_e = max_ae = 0.0
    times     = []
    residuals = []

    for row, pred in zip(rows, predictions):
        error  = pred - row["food_temp_c"]
        ae     = abs(error)
        sse    += error ** 2
        sum_ae += ae
        sum_e  += error
        max_ae  = max(max_ae, ae)
        times.append(row["time_sec"])
        residuals.append(error)

    rmse       = math.sqrt(sse / n) if n > 0 else float("inf")
    mae        = sum_ae / n         if n > 0 else float("inf")
    mean_error = sum_e / n          if n > 0 else float("inf")

    # Linear residual slope via ordinary least squares
    residual_slope = 0.0
    if n >= 2:
        mean_t = sum(times) / n
        mean_r = sum(residuals) / n
        num    = sum(
            (t - mean_t) * (r - mean_r)
            for t, r in zip(times, residuals)
        )
        den = sum((t - mean_t) ** 2 for t in times)
        if den > 0:
            residual_slope = num / den

    return {
        "sse":            sse,
        "rmse":           rmse,
        "mae":            mae,
        "mean_error":     mean_error,
        "max_abs_error":  max_ae,
        "residual_slope": residual_slope,
        "n":              n,
        "predictions":    predictions,
        "_rows":          rows,
    }


# ---------------------------------------------------------------------------
# Two-stage grid search
# ---------------------------------------------------------------------------

def two_stage_search(
    rows: list[dict],
    initial_temp_c: float,
    low: float,
    high: float,
    coarse_steps: int,
    fine_steps: int,
) -> tuple[float, dict]:
    """
    Stage 1: coarse search over [low, high] with coarse_steps points.
    Stage 2: fine search in ±5% interval around the coarse best.

    Returns (best_rate, metrics_dict).

    Warns when the optimum lands on a search boundary,
    which suggests the search interval should be expanded.
    """
    if low >= high:
        raise ValueError(
            f"--low must be less than --high. Got low={low}, high={high}."
        )
    if coarse_steps < 2:
        raise ValueError("--steps must be at least 2.")
    if fine_steps < 2:
        raise ValueError("--refine-steps must be at least 2.")

    def search(lo: float, hi: float, n: int) -> tuple[float, dict]:
        best_rate    = lo
        best_metrics = {"sse": float("inf")}
        step         = (hi - lo) / (n - 1)

        for i in range(n):
            rate    = lo + i * step
            metrics = compute_metrics(rows, rate, initial_temp_c)
            if metrics["sse"] < best_metrics["sse"]:
                best_metrics = metrics
                best_rate    = rate

        return best_rate, best_metrics

    # Stage 1
    best_coarse, _ = search(low, high, coarse_steps)

    # Stage 2 — narrow around coarse result
    margin    = (high - low) * 0.05
    fine_low  = max(low,  best_coarse - margin)
    fine_high = min(high, best_coarse + margin)

    best_rate, best_metrics = search(fine_low, fine_high, fine_steps)

    # Boundary warnings
    boundary_tol = (high - low) * 0.001
    if abs(best_rate - low) < boundary_tol:
        print(
            f"\n  WARNING: Best-fit k = {best_rate:.6f} /s is on the "
            f"lower search boundary ({low}). "
            "The true optimum may be outside the search range. "
            "Expand --low before accepting this result."
        )
    if abs(best_rate - high) < boundary_tol:
        print(
            f"\n  WARNING: Best-fit k = {best_rate:.6f} /s is on the "
            f"upper search boundary ({high}). "
            "The true optimum may be outside the search range. "
            "Expand --high before accepting this result."
        )

    return best_rate, best_metrics


# ---------------------------------------------------------------------------
# Structural adequacy (heuristic — NOT a formal F-test)
# ---------------------------------------------------------------------------

def structural_adequacy_test(
    rows: list[dict],
    k: float,
    initial_temp_c: float,
    low: float,
    high: float,
    coarse_steps: int,
    fine_steps: int,
) -> dict:
    """
    Heuristic structural adequacy comparison.

    Checks whether a two-parameter model (k + pan_temperature_offset)
    fits substantially better than the one-parameter model (k only).

    THIS IS NOT A FORMAL STATISTICAL F-TEST.
    It does not compute p-values, does not assume a specific
    error distribution, and should not be cited as one.
    It is a heuristic SSE comparison to flag potential structural
    inadequacy in the exponential heating model.

    If the two-parameter SSE is more than 10% lower than the
    one-parameter SSE, a structural warning is issued.
    That 10% threshold is an engineering choice, not a
    statistically derived significance level.

    Interpretation:
      structurally_adequate = True
        The exponential model shape appears adequate.
        Fitting a better k is likely to improve the fit.

      structurally_adequate = False
        A pan-temperature offset substantially reduces SSE.
        The model shape itself may be inadequate, not just k.
        Consider: more accurate pan-temperature measurement,
        a time-varying pan-temperature model, or a different
        functional form.
    """
    one_param_sse = compute_metrics(rows, k, initial_temp_c)["sse"]
    n             = len(rows)

    best_two_sse = one_param_sse
    best_offset  = 0.0

    for offset_int in range(-10, 11):
        offset        = float(offset_int)
        adjusted_rows = [
            {**r, "pan_temp_c": r["pan_temp_c"] + offset}
            for r in rows
        ]
        try:
            rate, metrics = two_stage_search(
                adjusted_rows, initial_temp_c,
                low, high, coarse_steps, fine_steps,
            )
        except ValueError:
            continue

        if metrics["sse"] < best_two_sse:
            best_two_sse = metrics["sse"]
            best_offset  = offset

    if one_param_sse > 0 and best_two_sse < one_param_sse:
        improvement  = (one_param_sse - best_two_sse) / one_param_sse
        heuristic_f  = (
            ((one_param_sse - best_two_sse) / 1.0)
            / (best_two_sse / max(n - 2, 1))
        )
    else:
        improvement = 0.0
        heuristic_f = 0.0

    structurally_adequate = improvement < 0.10

    return {
        "method": (
            "heuristic_sse_comparison_not_formal_F_test"
        ),
        "one_parameter_sse":     round(one_param_sse, 4),
        "two_parameter_sse":     round(best_two_sse, 4),
        "best_pan_offset_c":     best_offset,
        "sse_improvement":       round(improvement, 4),
        "heuristic_f_ratio":     round(heuristic_f, 4),
        "structurally_adequate": structurally_adequate,
        "threshold_note": (
            "10% SSE improvement threshold is an engineering choice, "
            "not a statistically derived significance level."
        ),
        "warning": (
            None if structurally_adequate else
            "W-FIT-STRUCTURAL: Two-parameter heuristic reduces SSE by "
            f"{improvement*100:.1f}%. The exponential model shape may be "
            "inadequate for this dataset. Consider measuring pan temperature "
            "more accurately, using a time-varying pan model, or a different "
            "functional form. "
            "Note: this is a heuristic comparison, NOT a formal F-test."
        ),
    }


# ---------------------------------------------------------------------------
# Parameter-uncertainty interval
# ---------------------------------------------------------------------------

def parameter_uncertainty_interval(
    time_points: list[float],
    k_values: list[float],
    initial_temp_c: float,
    pan_temp_c: float,
) -> list[dict]:
    """
    Computes a parameter-uncertainty interval for predicted temperature.

    IMPORTANT — THIS IS NOT A FULL PREDICTIVE INTERVAL.

    This interval captures only the spread of predictions caused
    by uncertainty in the fitted heating rate k (from bootstrap).

    It does NOT include:
      - Thermometer measurement error (±accuracy_c)
      - Pan-temperature measurement uncertainty
      - Process variability between cooking runs
      - Structural model error (wrong functional form)
      - Any uncertainty source other than k

    Do not interpret this as a complete uncertainty budget.
    A complete uncertainty budget requires propagating all
    sources of error through the model, which is not yet
    implemented in FoodLab v0.1.5.

    Method:
      For each time point, predict temperature using every
      bootstrap k sample. Report 2.5th and 97.5th percentiles.
    """
    if not k_values:
        return []

    intervals = []
    for t in time_points:
        preds = sorted([
            estimate_food_temperature(initial_temp_c, pan_temp_c, t, k)
            for k in k_values
        ])
        n        = len(preds)
        idx_low  = max(0,     int(0.025 * n))
        idx_high = min(n - 1, int(0.975 * n))

        intervals.append({
            "time_sec":       t,
            "pred_low_c":     round(preds[idx_low],  3),
            "pred_mean_c":    round(sum(preds) / n,   3),
            "pred_high_c":    round(preds[idx_high],  3),
            "interval_type":  "parameter_uncertainty_only",
            "excludes": [
                "thermometer_error",
                "pan_temperature_uncertainty",
                "process_variability",
                "structural_model_error",
            ],
        })

    return intervals


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def bootstrap_ci(
    calibration_groups: list[list[dict]],
    initial_temp_c: float,
    low: float,
    high: float,
    coarse_steps: int,
    fine_steps: int,
    n_bootstrap: int,
    seed: int,
) -> dict:
    """
    Estimates 95% confidence interval for heating_rate k.

    Resampling strategy:
      Multiple replicates (>1):
        Replicate-level bootstrap — resample whole experimental runs.
        This preserves temporal structure within each run.
        Statistically more defensible than row-level resampling.

      Single replicate:
        Row-level bootstrap — resample individual time points.
        Weaker statistically but the only option available.
        Temporal structure is broken by this approach.
        Documented explicitly in output.

    Returns dict with:
      mean, sd, ci_low, ci_high, n, mode, samples
    """
    rng      = random.Random(seed)
    samples  = []
    n_groups = len(calibration_groups)
    mode     = "replicate_level" if n_groups > 1 else "row_level_fallback"

    for _ in range(n_bootstrap):
        if mode == "replicate_level":
            chosen = [rng.choice(calibration_groups) for _ in range(n_groups)]
            rows   = [row for group in chosen for row in group]
        else:
            source = calibration_groups[0]
            rows   = [rng.choice(source) for _ in range(len(source))]

        try:
            rate, _ = two_stage_search(
                rows, initial_temp_c, low, high, coarse_steps, fine_steps
            )
            samples.append(rate)
        except ValueError:
            continue

    if not samples:
        return {}

    samples.sort()
    mean_k = sum(samples) / len(samples)
    sd_k   = math.sqrt(
        sum((s - mean_k) ** 2 for s in samples) / len(samples)
    )
    idx_low  = max(0,              int(0.025 * len(samples)))
    idx_high = min(len(samples)-1, int(0.975 * len(samples)))

    return {
        "mean":    mean_k,
        "sd":      sd_k,
        "ci_low":  samples[idx_low],
        "ci_high": samples[idx_high],
        "n":       len(samples),
        "mode":    mode,
        "mode_note": (
            "Replicate-level resampling preserves temporal structure."
            if mode == "replicate_level"
            else "Row-level fallback — temporal structure is broken. "
                 "Collect more replicates for a defensible CI."
        ),
        "samples": samples,
    }


# ---------------------------------------------------------------------------
# Quality label
# ---------------------------------------------------------------------------

def quality_label(
    rmse: float,
    thermometer_accuracy: float,
    residual_slope: float,
) -> str:
    """
    Contextual fit quality label.

    Normalises RMSE by thermometer accuracy so the label
    reflects instrument capability, not an absolute threshold.

    Thresholds (normalised RMSE):
      < 2×  good
      < 4×  acceptable
      >= 4× poor

    These thresholds are heuristic choices.
    Always evaluate fit quality in the context of the experiment.
    """
    normalized = (
        rmse / thermometer_accuracy
        if thermometer_accuracy > 0
        else float("inf")
    )

    if normalized < 2.0:
        label = "good"
    elif normalized < 4.0:
        label = "acceptable"
    else:
        label = "poor"

    slope_note = ""
    if abs(residual_slope) > 0.005:
        slope_note = (
            " | W-FIT-RESIDUAL-TREND: Residuals show systematic "
            "time trend. Constant-k model may be structurally inadequate."
        )

    return (
        f"{label}  "
        f"(RMSE={rmse:.3f}°C, "
        f"instrument±{thermometer_accuracy}°C, "
        f"normalized={normalized:.2f}×)"
        f"{slope_note}"
        f"  [{QUALITY_NOTE}]"
    )


# ---------------------------------------------------------------------------
# ASCII plot
# ---------------------------------------------------------------------------

def ascii_plot(
    rows: list[dict],
    predictions: list[float],
    intervals: list[dict] | None,
    width: int = 55,
    height: int = 14,
) -> None:
    """
    Renders ASCII temperature-vs-time chart.

    O = observed data point
    * = model prediction (best-fit k)
    . = parameter-uncertainty interval band (k uncertainty only)

    The interval band does NOT represent full prediction uncertainty.
    """
    all_temps = (
        [r["food_temp_c"] for r in rows]
        + predictions
    )
    if intervals:
        all_temps += [iv["pred_low_c"]  for iv in intervals]
        all_temps += [iv["pred_high_c"] for iv in intervals]

    t_min  = min(all_temps)
    t_max  = max(all_temps)
    t_rng  = t_max - t_min if t_max > t_min else 1.0

    times  = [r["time_sec"] for r in rows]
    tm_min = min(times)
    tm_max = max(times)
    tm_rng = tm_max - tm_min if tm_max > tm_min else 1.0

    def col(time_sec: float) -> int:
        return int((time_sec - tm_min) / tm_rng * (width - 1))

    def row_idx(temp_c: float) -> int:
        return int((t_max - temp_c) / t_rng * (height - 1))

    grid = [[" "] * width for _ in range(height)]

    # Parameter-uncertainty interval band
    if intervals:
        for iv in intervals:
            c      = col(iv["time_sec"])
            r_top  = row_idx(iv["pred_high_c"])
            r_bot  = row_idx(iv["pred_low_c"])
            for r in range(max(0, r_top), min(height, r_bot + 1)):
                if grid[r][c] == " ":
                    grid[r][c] = "."

    # Predictions
    for pred, obs_row in zip(predictions, rows):
        c = col(obs_row["time_sec"])
        r = row_idx(pred)
        if 0 <= r < height and 0 <= c < width:
            grid[r][c] = "*"

    # Observations (highest draw priority)
    for obs_row in rows:
        c = col(obs_row["time_sec"])
        r = row_idx(obs_row["food_temp_c"])
        if 0 <= r < height and 0 <= c < width:
            grid[r][c] = "O"

    print("\n  Temperature vs Time  (calibration data)")
    print(f"  {t_max:>6.1f}°C ┐")
    for line in grid:
        print(f"  {'':>8} │" + "".join(line))
    print(f"  {t_min:>6.1f}°C ┘")
    print(f"  {'':>10}" + "─" * width)
    print(
        f"  {'':>10}{tm_min:.0f}s"
        + " " * (width - 10)
        + f"{tm_max:.0f}s"
    )
    print()
    print(
        "  O = observed   "
        "* = predicted (best-fit k)   "
        ". = parameter-uncertainty interval (k only)"
    )
    print(
        "  Note: interval band captures k uncertainty only — "
        "not full prediction uncertainty."
    )


# ---------------------------------------------------------------------------
# Calibration artifact
# ---------------------------------------------------------------------------

def save_calibration_artifact(
    artifact: dict,
    experiment_id: str,
) -> Path:
    """
    Saves versioned calibration artifact.

    Directory structure:
        calibration/
            heating_rate/
                YYYY-MM-DD_EXP-ID.json   ← date-stamped record
                latest.json              ← convenience pointer

    The date-stamped file is never overwritten.
    latest.json always reflects the most recent run.
    """
    model_dir = CALIBRATION_DIR / "heating_rate"
    model_dir.mkdir(parents=True, exist_ok=True)

    date_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename  = f"{date_str}_{experiment_id}.json"
    path      = model_dir / filename

    with path.open("w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)

    latest = {
        "points_to": filename,
        "updated":   datetime.now(timezone.utc).isoformat(),
        "artifact":  artifact,
    }
    with (model_dir / "latest.json").open("w", encoding="utf-8") as f:
        json.dump(latest, f, indent=2)

    return path


# ---------------------------------------------------------------------------
# Residual CSV
# ---------------------------------------------------------------------------

def save_residual_csv(
    rows: list[dict],
    predictions: list[float],
    filepath: str,
) -> None:
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "time_sec",
            "observed_c",
            "pan_temp_c",
            "predicted_c",
            "residual_c",
        ])
        for row, pred in zip(rows, predictions):
            writer.writerow([
                row["time_sec"],
                row["food_temp_c"],
                row["pan_temp_c"],
                round(pred, 4),
                round(pred - row["food_temp_c"], 4),
            ])

    print(f"\n  Residuals saved to: {filepath}")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report(
    calibration_rate:     float,
    calibration_metrics:  dict,
    validation_metrics:   dict | None,
    bootstrap:            dict | None,
    replicate_rates:      list[float],
    structural:           dict,
    thermometer_accuracy: float,
    experiment_id:        str,
    n_calibration:        int,
    n_validation:         int,
    fingerprint:          str,
    args:                 argparse.Namespace,
) -> None:

    W = 65
    print("\n" + "=" * W)
    print(f"  FoodLab — Heating Rate Calibration Report  v{VERSION}")
    print("=" * W)

    print(f"\n  Experiment ID         : {experiment_id}")
    print(f"  Data fingerprint      : {fingerprint}")
    print(f"  Timestamp             : {datetime.now(timezone.utc).isoformat()}")
    print(f"  Calibration reps      : {n_calibration}")
    print(f"  Validation reps       : {n_validation}")
    print(f"  Thermometer accuracy  : ±{thermometer_accuracy}°C")

    # Replicate statistics
    if len(replicate_rates) > 1:
        mean_k = sum(replicate_rates) / len(replicate_rates)
        var_k  = sum((r - mean_k)**2 for r in replicate_rates) / len(replicate_rates)
        sd_k   = math.sqrt(var_k)
        cv_k   = (sd_k / mean_k * 100) if mean_k > 0 else float("inf")

        print("\n  REPLICATE FITS")
        print("  " + "-" * (W - 2))
        for i, rate in enumerate(replicate_rates, 1):
            print(f"  Replicate {i}           : k = {rate:.6f} /s")
        print(f"  Mean k                : {mean_k:.6f} /s")
        print(f"  Std deviation         : {sd_k:.6f} /s")
        print(f"  CV                    : {cv_k:.1f}%")
        print(f"  Min / Max             : {min(replicate_rates):.6f} / {max(replicate_rates):.6f} /s")

    # Calibration
    print("\n  CALIBRATION")
    print("  " + "-" * (W - 2))
    print(f"  Fitted k              : {calibration_rate:.6f} /s")
    print(f"  Observations used     : {calibration_metrics['n']}")
    print(f"  RMSE                  : {calibration_metrics['rmse']:.4f} °C")
    print(f"  MAE                   : {calibration_metrics['mae']:.4f} °C")
    print(f"  Mean error (bias)     : {calibration_metrics['mean_error']:+.4f} °C")
    print(f"  Max absolute error    : {calibration_metrics['max_abs_error']:.4f} °C")
    print(f"  Residual slope        : {calibration_metrics['residual_slope']:+.6f} °C/s")
    print(
        f"  Fit quality           : "
        f"{quality_label(calibration_metrics['rmse'], thermometer_accuracy, calibration_metrics['residual_slope'])}"
    )

    # Validation
    if validation_metrics:
        print("\n  VALIDATION  (held-out replicate)")
        print("  " + "-" * (W - 2))
        print(f"  Observations used     : {validation_metrics['n']}")
        print(f"  Validation RMSE       : {validation_metrics['rmse']:.4f} °C")
        print(f"  Validation MAE        : {validation_metrics['mae']:.4f} °C")
        print(f"  Mean error (bias)     : {validation_metrics['mean_error']:+.4f} °C")
        print(f"  Max absolute error    : {validation_metrics['max_abs_error']:.4f} °C")
        print(
            f"  Fit quality           : "
            f"{quality_label(validation_metrics['rmse'], thermometer_accuracy, validation_metrics['residual_slope'])}"
        )

    # Structural adequacy
    print("\n  STRUCTURAL ADEQUACY  (heuristic comparison — NOT a formal F-test)")
    print("  " + "-" * (W - 2))
    print(f"  Method                : {structural['method']}")
    print(f"  One-parameter SSE     : {structural['one_parameter_sse']}")
    print(f"  Two-parameter SSE     : {structural['two_parameter_sse']}")
    print(f"  Best pan offset       : {structural['best_pan_offset_c']:+.1f} °C")
    print(f"  SSE improvement       : {structural['sse_improvement']*100:.1f}%")
    print(f"  Heuristic F-ratio     : {structural['heuristic_f_ratio']:.2f}")
    print(f"  Threshold note        : {structural['threshold_note']}")
    print(
        f"  Structurally adequate : "
        f"{'yes' if structural['structurally_adequate'] else 'NO — see warning below'}"
    )
    if structural["warning"]:
        print(f"\n  ⚠  {structural['warning']}")

    # Bootstrap
    if bootstrap:
        print(
            f"\n  BOOTSTRAP CI  "
            f"(95%, n={bootstrap['n']}, {bootstrap['mode']})"
        )
        print("  " + "-" * (W - 2))
        print(f"  Mode note             : {bootstrap['mode_note']}")
        print(f"  Bootstrap mean k      : {bootstrap['mean']:.6f} /s")
        print(f"  Bootstrap SD          : {bootstrap['sd']:.6f} /s")
        print(
            f"  95% CI                : "
            f"[{bootstrap['ci_low']:.6f}, {bootstrap['ci_high']:.6f}] /s"
        )

    # Predicted vs observed table
    print("\n  PREDICTED vs OBSERVED  (calibration data)")
    print("  " + "-" * (W - 2))
    print(
        f"  {'Time (s)':>8}  "
        f"{'Observed':>10}  "
        f"{'Pan °C':>8}  "
        f"{'Predicted':>10}  "
        f"{'Residual':>10}"
    )
    print("  " + "-" * (W - 2))
    for row, pred in zip(
        calibration_metrics["_rows"],
        calibration_metrics["predictions"],
    ):
        print(
            f"  {row['time_sec']:>8.0f}  "
            f"{row['food_temp_c']:>10.2f}  "
            f"{row['pan_temp_c']:>8.1f}  "
            f"{pred:>10.4f}  "
            f"{pred - row['food_temp_c']:>+10.4f}"
        )

    # Scientific cautions
    print("\n  SCIENTIFIC CAUTIONS")
    print("  " + "-" * (W - 2))
    print("  k and T_pan are partially confounded in constant-pan mode.")
    print("  A fitted k is only valid under conditions similar to")
    print("  those of the calibration experiment.")
    print("  The parameter-uncertainty interval captures k uncertainty only.")
    print("  It does not represent thermometer error, pan-temperature")
    print("  uncertainty, process variability, or structural model error.")
    print("  Validate using an independent replicate before using in engine.")

    # Parameter block for model_parameters.json
    status = (
        "experimentally_fitted_and_independently_validated"
        if validation_metrics
        else "experimentally_fitted_not_yet_validated"
    )
    source_ids = (
        [f"{experiment_id}-R{i+1}" for i in range(n_calibration)]
        if n_calibration > 1
        else [experiment_id]
    )

    param_block: dict = {
        "heating_rate_per_second": {
            "value":                round(calibration_rate, 6),
            "unit":                 "1/second",
            "role":                 "model_parameter",
            "status":               status,
            "calibration_rmse_c":   round(calibration_metrics["rmse"], 4),
            "calibration_mae_c":    round(calibration_metrics["mae"], 4),
            "validation_rmse_c": (
                round(validation_metrics["rmse"], 4)
                if validation_metrics else None
            ),
            "replicate_count":    n_calibration,
            "source_ids":         source_ids,
            "data_fingerprint":   fingerprint,
        }
    }

    if bootstrap:
        param_block["heating_rate_per_second"].update({
            "confidence_interval_95": [
                round(bootstrap["ci_low"],  6),
                round(bootstrap["ci_high"], 6),
            ],
            "bootstrap_sd":    round(bootstrap["sd"], 6),
            "bootstrap_mode":  bootstrap["mode"],
        })

    print("\n  UPDATE model_parameters.json WITH:")
    print("  " + "-" * (W - 2))
    print(json.dumps(param_block, indent=4))
    print("=" * W)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()

    if not args.data:
        print(
            "\n  ERROR: No data files provided.\n"
            "  Use: --data experiments/EXP-0001-R1/temperatures.csv\n"
            "  See experiments/EXP-0001/temperatures.csv for format."
        )
        return 1

    fingerprint = fingerprint_files(args.data)

    # Load and validate all replicates
    all_replicates: list[list[dict]] = []
    for filepath in args.data:
        try:
            rows = load_replicate(filepath, args.initial_temp, args.pan)
        except (FileNotFoundError, ValueError) as exc:
            print(f"\n  ERROR: {exc}")
            return 1

        for w in validate_replicate(rows, args.initial_temp, filepath):
            print(f"  WARNING: {w}")

        all_replicates.append(rows)

    n_replicates = len(all_replicates)

    # Calibration / validation split
    val_idx = args.validation_replicate
    if val_idx is not None:
        if not (1 <= val_idx <= n_replicates):
            print(
                f"\n  ERROR: --validation-replicate must be "
                f"between 1 and {n_replicates}. Got {val_idx}."
            )
            return 1
        validation_rows    = all_replicates[val_idx - 1]
        calibration_groups = [
            r for i, r in enumerate(all_replicates, 1)
            if i != val_idx
        ]
    else:
        validation_rows    = None
        calibration_groups = all_replicates

    calibration_rows = [row for group in calibration_groups for row in group]
    n_calibration    = len(calibration_groups)
    n_validation     = 1 if validation_rows else 0

    if len(calibration_rows) < 2:
        print("\n  ERROR: Calibration set has fewer than 2 observations.")
        return 1

    # Fit each replicate separately for variance reporting
    replicate_rates: list[float] = []
    for group in calibration_groups:
        try:
            rate, _ = two_stage_search(
                group, args.initial_temp,
                args.low, args.high,
                args.steps, args.refine_steps,
            )
            replicate_rates.append(rate)
        except ValueError as exc:
            print(f"\n  ERROR: {exc}")
            return 1

    # Fit combined calibration set
    try:
        calibration_rate, calibration_metrics = two_stage_search(
            calibration_rows, args.initial_temp,
            args.low, args.high,
            args.steps, args.refine_steps,
        )
    except ValueError as exc:
        print(f"\n  ERROR: {exc}")
        return 1

    calibration_metrics["_rows"] = calibration_rows

    # Validation metrics
    validation_metrics = None
    if validation_rows:
        validation_metrics = compute_metrics(
            validation_rows, calibration_rate, args.initial_temp
        )

    # Structural adequacy test
    print("\n  Running structural adequacy test...")
    structural = structural_adequacy_test(
        calibration_rows, calibration_rate, args.initial_temp,
        args.low, args.high, args.steps, args.refine_steps,
    )

    # Bootstrap
    bootstrap = None
    if args.bootstrap > 0:
        mode_label = (
            "replicate-level"
            if len(calibration_groups) > 1
            else "row-level fallback"
        )
        print(
            f"\n  Running bootstrap "
            f"({args.bootstrap} iterations, {mode_label}, "
            f"seed={args.bootstrap_seed})..."
        )
        bootstrap = bootstrap_ci(
            calibration_groups,
            args.initial_temp,
            args.low, args.high,
            args.steps, args.refine_steps,
            args.bootstrap,
            args.bootstrap_seed,
        )

    # Parameter-uncertainty intervals
    intervals = None
    if bootstrap and bootstrap.get("samples"):
        time_points = sorted({r["time_sec"] for r in calibration_rows})
        mean_pan    = (
            sum(r["pan_temp_c"] for r in calibration_rows)
            / len(calibration_rows)
        )
        intervals = parameter_uncertainty_interval(
            time_points,
            bootstrap["samples"],
            args.initial_temp,
            mean_pan,
        )

    # Print full report
    print_report(
        calibration_rate=calibration_rate,
        calibration_metrics=calibration_metrics,
        validation_metrics=validation_metrics,
        bootstrap=bootstrap,
        replicate_rates=replicate_rates,
        structural=structural,
        thermometer_accuracy=args.thermometer_accuracy,
        experiment_id=args.experiment_id,
        n_calibration=n_calibration,
        n_validation=n_validation,
        fingerprint=fingerprint,
        args=args,
    )

    # ASCII plot
    if not args.no_plot:
        ascii_plot(
            calibration_metrics["_rows"],
            calibration_metrics["predictions"],
            intervals,
        )

    # Save residuals
    if args.save_residuals:
        save_residual_csv(
            calibration_rows,
            calibration_metrics["predictions"],
            args.save_residuals,
        )

    # Save calibration artifact
    if not args.no_artifact:
        status = (
            "experimentally_fitted_and_independently_validated"
            if validation_metrics
            else "experimentally_fitted_not_yet_validated"
        )
        source_ids = (
            [f"{args.experiment_id}-R{i+1}" for i in range(n_calibration)]
            if n_calibration > 1
            else [args.experiment_id]
        )
        artifact = {
            "tool_version":      VERSION,
            "experiment_id":     args.experiment_id,
            "data_fingerprint":  fingerprint,
            "timestamp":         datetime.now(timezone.utc).isoformat(),
            "fitted_k":          round(calibration_rate, 6),
            "status":            status,
            "source_ids":        source_ids,
            "calibration_rmse_c": round(calibration_metrics["rmse"], 4),
            "calibration_mae_c":  round(calibration_metrics["mae"], 4),
            "validation_rmse_c": (
                round(validation_metrics["rmse"], 4)
                if validation_metrics else None
            ),
            "bootstrap": (
                {
                    "mode":     bootstrap["mode"],
                    "mode_note": bootstrap["mode_note"],
                    "mean":     round(bootstrap["mean"], 6),
                    "sd":       round(bootstrap["sd"], 6),
                    "ci_low":   round(bootstrap["ci_low"], 6),
                    "ci_high":  round(bootstrap["ci_high"], 6),
                    "n":        bootstrap["n"],
                }
                if bootstrap else None
            ),
            "structural_adequacy": structural,
            "parameter_uncertainty_intervals": (
                {
                    "type":     "parameter_uncertainty_only",
                    "excludes": [
                        "thermometer_error",
                        "pan_temperature_uncertainty",
                        "process_variability",
                        "structural_model_error",
                    ],
                    "intervals": intervals,
                }
                if intervals else None
            ),
        }

        artifact_path = save_calibration_artifact(artifact, args.experiment_id)
        print(f"\n  Calibration artifact saved to : {artifact_path}")
        print(
            f"  Latest pointer updated        : "
            f"{artifact_path.parent / 'latest.json'}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
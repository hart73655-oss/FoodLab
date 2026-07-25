"""
tools/benchmark_runner.py
FoodLab v0.2.3

Changes from v0.2.2:
  - evaluable = passed + failed only (excludes missing and suppressed)
  - missing dimensions tracked and reported separately
  - save_benchmark_results now preserves full analysis:
      physics health, readiness, root-cause analysis,
      summary counts, benchmark status, runner version
  - save_benchmark_results accepts root_causes parameter
  - Summary section reports evaluable/suppressed/missing separately
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR     = PROJECT_ROOT / "data"
BENCH_DIR    = PROJECT_ROOT / "experiments" / "benchmark"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.loader import (
    load_ingredients,
    load_model_parameters,
    load_recipes,
    resolve_recipe,
)
from engine.simulate import simulate
from models.perception import generate_perceptual_profile


RUNNER_VERSION = "0.2.3"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"FoodLab Benchmark Runner v{RUNNER_VERSION}",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--show-evidence",
        action="store_true",
        help="Print evidence list for each perceptual dimension.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print full physics outputs for each condition.",
    )
    parser.add_argument(
        "--benchmark",
        type=str,
        default=None,
        help=(
            "Path to benchmark JSON. "
            "Defaults to experiments/benchmark/expected_profile.json"
        ),
    )
    parser.add_argument(
        "--compare",
        type=str,
        default=None,
        help="Path to previous benchmark result JSON for progress tracking.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_benchmark(filepath: Path) -> dict:
    with filepath.open("r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_condition(
    condition: dict,
    recipe: dict,
    ingredients: dict,
    parameters: dict,
) -> dict:
    physics    = simulate(
        recipe_id="scrambled_eggs_basic",
        recipe=recipe,
        ingredients=ingredients,
        parameters=parameters,
        pan_temperature_c=condition["pan_temperature_c"],
        duration_min=condition["duration_min"],
        time_step_sec=1.0,
    )
    perception = generate_perceptual_profile(physics)
    return {
        "condition_id": condition["condition_id"],
        "label":        condition["label"],
        "physics":      physics,
        "perception":   perception,
    }


# ---------------------------------------------------------------------------
# Error calculation
# ---------------------------------------------------------------------------

def range_error(value: float, min_val: float, max_val: float) -> float:
    if value < min_val:
        return round(value - min_val, 4)
    if value > max_val:
        return round(value - max_val, 4)
    return 0.0


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

def evaluate_condition(result: dict, condition: dict) -> dict:
    expected   = condition["expected"]
    physics    = result["physics"]["outputs"]
    perception = result["perception"]["dimensions"]

    value_sources: dict[str, float | None] = {
        "protein_denaturation_fraction": physics.get(
            "protein_denaturation_fraction", None
        ),
    }
    for dim_name, dim_data in perception.items():
        value_sources[dim_name] = dim_data.get("score", None)

    results = {}
    for dim_name, exp in expected.items():
        raw_value = value_sources.get(dim_name)
        dim_data  = perception.get(dim_name, {})
        evidence  = dim_data.get("evidence", [])

        if raw_value is None:
            results[dim_name] = {
                "status":       "MISSING",
                "value":        None,
                "expected_min": exp["min"],
                "expected_max": exp["max"],
                "error":        None,
                "label":        exp["label"],
                "note":         exp.get("note", ""),
                "evidence":     evidence,
            }
            continue

        if dim_data.get("suppressed", False):
            results[dim_name] = {
                "status":       "SUPPRESSED",
                "value":        round(raw_value, 4),
                "expected_min": exp["min"],
                "expected_max": exp["max"],
                "error":        None,
                "label":        exp["label"],
                "note":         dim_data.get("suppression_reason", ""),
                "evidence":     evidence,
            }
            continue

        error  = range_error(raw_value, exp["min"], exp["max"])
        passed = error == 0.0
        results[dim_name] = {
            "status":       "PASS" if passed else "FAIL",
            "value":        round(raw_value, 4),
            "expected_min": exp["min"],
            "expected_max": exp["max"],
            "error":        error,
            "label":        exp["label"],
            "note":         exp.get("note", ""),
            "evidence":     evidence,
        }

    return results


# ---------------------------------------------------------------------------
# Dimension counts — correct evaluable calculation
# ---------------------------------------------------------------------------

def count_dimensions(all_evaluations: list[dict]) -> dict[str, int]:
    """
    Returns counts by status.

    evaluable = passed + failed only.
    suppressed and missing are not evaluable.
    """
    counts = {
        "total":      0,
        "pass":       0,
        "fail":       0,
        "suppressed": 0,
        "missing":    0,
    }
    for ev in all_evaluations:
        for dim_result in ev.values():
            counts["total"] += 1
            status = dim_result["status"]
            if status == "PASS":
                counts["pass"] += 1
            elif status == "FAIL":
                counts["fail"] += 1
            elif status == "SUPPRESSED":
                counts["suppressed"] += 1
            elif status == "MISSING":
                counts["missing"] += 1

    counts["evaluable"] = counts["pass"] + counts["fail"]
    return counts


# ---------------------------------------------------------------------------
# Root-cause analysis
# ---------------------------------------------------------------------------

CAUSAL_PIPELINE = [
    {
        "root_cause":    "Heating model (heating_rate parameter)",
        "fix":           "Run EXP-0001. Fit heating_rate with fit_heating_rate.py.",
        "drives":        [
            "protein_denaturation_fraction",
            "tenderness",
            "creaminess",
        ],
        "mechanism":     (
            "Heating rate controls temperature trajectory. "
            "If too fast, denaturation saturates at 1.0 under every condition. "
            "All conditions predict equal denaturation regardless of pan temp."
        ),
        "signature":     "denaturation == 1.0 under all conditions",
        "pipeline_step": 1,
        "health_key":    "Heating model",
    },
    {
        "root_cause":    "Evaporation model (evaporation_rate parameter)",
        "fix":           "Run EXP-0002. Weigh food before and after cooking.",
        "drives":        ["juiciness", "creaminess", "surface_crunch"],
        "mechanism":     (
            "Evaporation rate controls water loss. "
            "If too low, juiciness barely changes across conditions. "
            "High and low heat produce almost identical moisture outputs."
        ),
        "signature":     "juiciness variation < 0.05 across all conditions",
        "pipeline_step": 2,
        "health_key":    "Evaporation model",
    },
    {
        "root_cause":    "Maillard browning model (browning parameters)",
        "fix":           "Calibrate heating_rate first. Then adjust browning onset and rate.",
        "drives":        ["roastedness", "surface_crunch", "bitterness_burn"],
        "mechanism":     (
            "Browning onset uses a sigmoid centered at 140°C. "
            "With placeholder heating, surface temperature barely reaches onset. "
            "After temperature calibration, browning should activate more clearly."
        ),
        "signature":     "roastedness < 0.01 even at 200°C pan temperature",
        "pipeline_step": 3,
        "health_key":    "Maillard model",
    },
    {
        "root_cause":    "Burn model (burn_rate_multiplier, sustained exposure)",
        "fix":           "Calibrate browning first. Burn depends on browning accumulation.",
        "drives":        ["bitterness_burn"],
        "mechanism":     (
            "Burn requires browning_index > 0.5 AND sustained high-temp exposure. "
            "If browning never accumulates, burn index stays at zero. "
            "Fix the Maillard model upstream before addressing burn."
        ),
        "signature":     "bitterness_burn == 0.0 under all conditions",
        "pipeline_step": 4,
        "health_key":    "Burn model",
    },
]


def compute_root_cause_analysis(
    all_results: list[dict],
    all_evaluations: list[dict],
) -> list[dict]:
    dim_errors:     dict[str, list[float]] = {}
    dim_suppressed: dict[str, int]         = {}

    for ev in all_evaluations:
        for dim_name, dim_result in ev.items():
            err = dim_result.get("error")
            if err is not None:
                dim_errors.setdefault(dim_name, []).append(abs(err))
            if dim_result.get("status") == "SUPPRESSED":
                dim_suppressed[dim_name] = dim_suppressed.get(dim_name, 0) + 1

    all_denat  = [
        r["physics"]["outputs"].get("protein_denaturation_fraction", 0.0)
        for r in all_results
    ]
    all_juice, all_roast, all_bitter = [], [], []
    for r in all_results:
        dims = r["perception"]["dimensions"]
        all_juice.append(dims.get("juiciness",       {}).get("score", 0.0) or 0.0)
        all_roast.append(dims.get("roastedness",     {}).get("score", 0.0) or 0.0)
        all_bitter.append(dims.get("bitterness_burn",{}).get("score", 0.0) or 0.0)

    diagnoses = []
    for cause in CAUSAL_PIPELINE:
        failing_dims    = []
        total_error     = 0.0
        suppressed_dims = 0

        for dim_name in cause["drives"]:
            errors = dim_errors.get(dim_name, [])
            n_supp = dim_suppressed.get(dim_name, 0)
            suppressed_dims += n_supp

            if errors:
                mean_err = sum(errors) / len(errors)
                if mean_err > 0.01:
                    failing_dims.append({
                        "dimension":  dim_name,
                        "mean_error": round(mean_err, 4),
                    })
                    total_error += mean_err

        confidence         = 0.5
        signature_observed = False
        evidence_notes     = []
        step               = cause["pipeline_step"]

        if step == 1:
            if all(d >= 0.99 for d in all_denat):
                confidence         = 0.95
                signature_observed = True
                evidence_notes.append(
                    "Denaturation saturates at 1.0 under all 4 conditions. "
                    "Signature of an overestimated heating rate."
                )
            elif all(d >= 0.85 for d in all_denat):
                confidence = 0.75
                evidence_notes.append(
                    "Denaturation uniformly high across all conditions."
                )

        elif step == 2:
            juice_range = max(all_juice) - min(all_juice) if all_juice else 0.0
            if juice_range < 0.05:
                confidence         = 0.88
                signature_observed = True
                evidence_notes.append(
                    f"Juiciness range: {juice_range:.4f}. "
                    "Expected > 0.5. Evaporation barely responds to temperature."
                )
            evidence_notes.append(
                "Note: creaminess is a shared failure with heating model. "
                "Cannot isolate evaporation contribution until heating is calibrated."
            )

        elif step == 3:
            if all(r < 0.01 for r in all_roast):
                confidence         = 0.82
                signature_observed = True
                evidence_notes.append(
                    "Roastedness < 0.01 at all conditions including 200°C. "
                    "Browning model is not activating."
                )

        elif step == 4:
            if all(b < 0.01 for b in all_bitter):
                confidence         = 0.70
                signature_observed = True
                evidence_notes.append(
                    "Burn bitterness is zero everywhere. "
                    "Expected when browning never accumulates."
                )

        diagnoses.append({
            "pipeline_step":         cause["pipeline_step"],
            "root_cause":            cause["root_cause"],
            "fix":                   cause["fix"],
            "drives":                cause["drives"],
            "mechanism":             cause["mechanism"],
            "signature":             cause["signature"],
            "signature_observed":    signature_observed,
            "failing_dimensions":    failing_dims,
            "suppressed_dimensions": suppressed_dims,
            "total_error":           round(total_error, 4),
            "confidence":            round(confidence, 2),
            "evidence":              evidence_notes,
            "health_key":            cause["health_key"],
        })

    return sorted(diagnoses, key=lambda d: d["pipeline_step"])


# ---------------------------------------------------------------------------
# Physics health — uncertainty-aware
# ---------------------------------------------------------------------------

def _health_status(
    errors: list[float],
    suppressed_count: int,
    signature_observed: bool,
    label: str,
) -> dict:
    if signature_observed:
        return {
            "status":     "✗ Needs calibration",
            "mean_error": round(sum(errors) / len(errors), 4) if errors else None,
            "note":       label,
            "basis":      "signature_observed",
        }
    if suppressed_count > 0 and not errors:
        return {
            "status":     "? Insufficient evidence",
            "mean_error": None,
            "note":       label,
            "basis":      f"{suppressed_count} output(s) suppressed — not evaluable",
        }
    if not errors:
        return {
            "status":     "? Not evaluated",
            "mean_error": None,
            "note":       label,
            "basis":      "no evaluable outputs",
        }
    mean_err = sum(errors) / len(errors)
    if mean_err < 0.05:
        status = "✓ Supported"
    elif mean_err < 0.20:
        status = "⚠ Weak"
    else:
        status = "✗ Needs calibration"
    return {
        "status":     status,
        "mean_error": round(mean_err, 4),
        "note":       label,
        "basis":      f"mean error from {len(errors)} evaluable output(s)",
    }


def compute_physics_health(
    all_results: list[dict],
    all_evaluations: list[dict],
    root_causes: list[dict],
) -> dict:
    signature_map: dict[str, bool] = {
        rc["health_key"]: rc["signature_observed"]
        for rc in root_causes
    }

    model_dim_map = {
        "Heating model":     ["protein_denaturation_fraction", "tenderness"],
        "Evaporation model": ["juiciness"],
        "Maillard model":    ["roastedness", "surface_crunch"],
        "Burn model":        ["bitterness_burn"],
    }
    model_labels = {
        "Heating model":     "Drives temperature → denaturation → tenderness",
        "Evaporation model": "Drives water loss → juiciness → creaminess",
        "Maillard model":    "Drives browning → roastedness → crunch",
        "Burn model":        "Drives burn → bitterness",
    }

    model_errors:     dict[str, list[float]] = {}
    model_suppressed: dict[str, int]         = {}

    for ev in all_evaluations:
        for model_name, dims in model_dim_map.items():
            for dim_name in dims:
                if dim_name not in ev:
                    continue
                dim_result = ev[dim_name]
                err        = dim_result.get("error")
                if err is not None:
                    model_errors.setdefault(model_name, []).append(abs(err))
                if dim_result.get("status") == "SUPPRESSED":
                    model_suppressed[model_name] = (
                        model_suppressed.get(model_name, 0) + 1
                    )

    models = {}
    for model_name, label in model_labels.items():
        models[model_name] = _health_status(
            errors=             model_errors.get(model_name, []),
            suppressed_count=   model_suppressed.get(model_name, 0),
            signature_observed= signature_map.get(model_name, False),
            label=              label,
        )

    statuses             = [m["status"] for m in models.values()]
    n_calibration_needed = sum(1 for s in statuses if "Needs calibration" in s)
    n_insufficient       = sum(1 for s in statuses if "Insufficient" in s
                               or "Not evaluated" in s)
    n_supported          = sum(1 for s in statuses if "Supported" in s)

    if n_calibration_needed >= 2:
        readiness = "LOW — calibration required before meaningful evaluation"
    elif n_calibration_needed == 1:
        readiness = "PARTIAL — one model requires calibration"
    elif n_insufficient >= 2:
        readiness = "UNCERTAIN — insufficient evaluable evidence"
    elif n_supported == len(models):
        readiness = "GOOD — all models have supported outputs"
    else:
        readiness = "MIXED — some models need attention"

    return {
        "models":    models,
        "readiness": readiness,
    }


# ---------------------------------------------------------------------------
# Progress tracking
# ---------------------------------------------------------------------------

def compute_progress(
    current_evaluations: list[dict],
    previous_path: Path,
) -> dict | None:
    if not previous_path.exists():
        return None
    try:
        with previous_path.open("r", encoding="utf-8") as f:
            previous = json.load(f)
    except (json.JSONDecodeError, KeyError):
        return None

    def extract_counts(evaluations: list[dict]) -> tuple[dict, list[float]]:
        counts: dict[str, int] = {
            "pass": 0, "fail": 0, "suppressed": 0, "missing": 0
        }
        errors: list[float] = []
        for ev in evaluations:
            for dim_result in ev.values():
                status = dim_result.get("status", "MISSING").lower()
                if status in counts:
                    counts[status] += 1
                err = dim_result.get("error")
                if err is not None:
                    errors.append(abs(err))
        counts["evaluable"] = counts["pass"] + counts["fail"]
        return counts, errors

    def extract_evaluations(saved: dict) -> list[dict]:
        return [c["evaluation"] for c in saved.get("conditions", [])]

    curr_counts, curr_errors = extract_counts(current_evaluations)
    prev_evaluations         = extract_evaluations(previous)
    prev_counts, prev_errors = extract_counts(prev_evaluations)

    curr_mae = sum(curr_errors) / len(curr_errors) if curr_errors else 0.0
    prev_mae = sum(prev_errors) / len(prev_errors) if prev_errors else 0.0

    return {
        "curr_pass":         curr_counts["pass"],
        "curr_fail":         curr_counts["fail"],
        "curr_suppressed":   curr_counts["suppressed"],
        "curr_evaluable":    curr_counts["evaluable"],
        "prev_pass":         prev_counts.get("pass", 0),
        "prev_fail":         prev_counts.get("fail", 0),
        "prev_suppressed":   prev_counts.get("suppressed", 0),
        "prev_evaluable":    prev_counts.get("evaluable", 0),
        "pass_change":       curr_counts["pass"]       - prev_counts.get("pass", 0),
        "fail_change":       curr_counts["fail"]       - prev_counts.get("fail", 0),
        "suppressed_change": curr_counts["suppressed"] - prev_counts.get("suppressed", 0),
        "curr_mae":          round(curr_mae, 4),
        "prev_mae":          round(prev_mae, 4),
        "mae_change":        round(curr_mae - prev_mae, 4),
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_benchmark_report(
    benchmark: dict,
    all_results: list[dict],
    all_evaluations: list[dict],
    root_causes: list[dict],
    health: dict,
    counts: dict[str, int],
    show_evidence: bool = False,
    verbose: bool = False,
    previous_path: Path | None = None,
) -> None:
    W = 82

    print("\n" + "=" * W)
    print(f"  FoodLab Benchmark Report  —  {benchmark['benchmark_id']}")
    print(f"  Runner    : v{RUNNER_VERSION}")
    print(f"  Status    : {benchmark['status']}")
    print(f"  Timestamp : {datetime.now(timezone.utc).isoformat()}")
    print("=" * W)

    # Physics Health
    print("\n  PHYSICS HEALTH")
    print("  " + "-" * (W - 2))
    for model_name, model_health in health["models"].items():
        basis = model_health.get("basis", "")
        mean  = model_health.get("mean_error")

        if basis == "signature_observed":
            if mean is not None:
                detail = f"signature observed  mean error {mean:.4f}"
            else:
                detail = "failure signature observed"
        elif mean is not None:
            detail = f"mean error {mean:.4f}"
        else:
            detail = basis

        print(
            f"  {model_name:<28}  "
            f"{model_health['status']:<28}  "
            f"{detail}"
        )
    print(f"\n  Overall readiness : {health['readiness']}")
    print(
        f"  Evaluable         : {counts['evaluable']} / {counts['total']}  "
        f"Suppressed: {counts['suppressed']}  "
        f"Missing: {counts['missing']}"
    )

    # Progress tracking
    if previous_path:
        progress = compute_progress(all_evaluations, previous_path)
        if progress:
            print("\n  PROGRESS vs PREVIOUS BENCHMARK")
            print("  " + "-" * (W - 2))

            def delta(n: int) -> str:
                return f"+{n}" if n > 0 else str(n)

            print(
                f"  PASS       : "
                f"{progress['prev_pass']} → {progress['curr_pass']}"
                f"  ({delta(progress['pass_change'])})"
            )
            print(
                f"  FAIL       : "
                f"{progress['prev_fail']} → {progress['curr_fail']}"
                f"  ({delta(progress['fail_change'])})"
            )
            print(
                f"  SUPPRESSED : "
                f"{progress['prev_suppressed']} → {progress['curr_suppressed']}"
                f"  ({delta(progress['suppressed_change'])})"
            )
            mae_dir = (
                "↓ improved"  if progress["mae_change"] < 0
                else "↑ worsened" if progress["mae_change"] > 0
                else "→ unchanged"
            )
            print(
                f"  Mean error : "
                f"{progress['prev_mae']:.4f} → {progress['curr_mae']:.4f}"
                f"  ({mae_dir})"
            )

    # Per-condition results
    for result, evaluation, condition in zip(
        all_results, all_evaluations, benchmark["conditions"]
    ):
        physics_conf = result["perception"].get("physics_confidence_score", 0.0)
        perc_conf    = result["perception"].get("perceptual_confidence", "unknown")

        print(
            f"\n  {condition['condition_id']}  {condition['label']}"
            f"  |  Pan: {condition['pan_temperature_c']}°C"
            f"  Duration: {condition['duration_min']} min"
        )
        print(
            f"  Physics confidence: {physics_conf:.2f}  "
            f"Perceptual confidence: {perc_conf}"
        )

        if verbose:
            out = result["physics"]["outputs"]
            print(f"  Temperature : {out['estimated_final_temperature_c']}°C")
            print(f"  Surface temp: {out['effective_surface_temperature_c']}°C")
            print(f"  Water loss  : {out['estimated_water_loss_g']} g")
            print(f"  Browning    : {out['browning_index']}")
            print(f"  Burn        : {out['burn_index']}")

        print("  " + "-" * (W - 2))
        print(
            f"  {'Dimension':<32}"
            f"{'Value':>7}"
            f"{'Expected':>16}"
            f"{'Error':>8}"
            f"{'Status':>14}"
        )
        print("  " + "-" * (W - 2))

        for dim_name, dim_result in evaluation.items():
            status  = dim_result["status"]
            value   = dim_result["value"]
            exp_min = dim_result["expected_min"]
            exp_max = dim_result["expected_max"]
            error   = dim_result["error"]

            value_str = f"{value:.4f}" if value is not None else "N/A"
            exp_str   = f"[{exp_min:.2f}, {exp_max:.2f}]"
            error_str = (
                f"{error:+.4f}" if error is not None and error != 0.0
                else ("  0.000"  if error == 0.0 else "    N/A")
            )
            status_display = {
                "PASS":       "PASS  ✓",
                "FAIL":       "FAIL  ✗",
                "SUPPRESSED": "SUPPRESSED",
                "MISSING":    "MISSING",
            }.get(status, status)

            print(
                f"  {dim_name:<32}"
                f"{value_str:>7}"
                f"{exp_str:>16}"
                f"{error_str:>8}"
                f"  {status_display}"
            )

            if show_evidence and dim_result.get("evidence"):
                for ev in dim_result["evidence"]:
                    print(f"      ↓ {ev}")

    # Root-cause analysis
    print("\n  " + "=" * (W - 2))
    print("  ROOT CAUSE ANALYSIS  (causal pipeline order)")
    print("  " + "-" * (W - 2))
    print("  Fixing upstream causes resolves multiple downstream failures.")
    print()

    for rc in root_causes:
        sig_marker = "✓ observed" if rc["signature_observed"] else "— not confirmed"
        print(f"  Step {rc['pipeline_step']}  {rc['root_cause']}")
        print(f"    Confidence     : {rc['confidence']:.2f}  ({sig_marker})")
        print(f"    Signature      : {rc['signature']}")
        print(f"    Mechanism      : {rc['mechanism']}")
        print(f"    Drives         : {', '.join(rc['drives'])}")
        if rc["failing_dimensions"]:
            failing_str = ", ".join(
                f"{d['dimension']} (err {d['mean_error']:.4f})"
                for d in rc["failing_dimensions"]
            )
            print(f"    Failing dims   : {failing_str}")
        if rc["suppressed_dimensions"] > 0:
            print(
                f"    Suppressed checks : {rc['suppressed_dimensions']} "
                "condition-dimension pairs "
                "(not evaluable — cannot rule this cause out)"
            )
        for ev in rc["evidence"]:
            print(f"    Evidence       : {ev}")
        print(f"    Recommended fix: {rc['fix']}")
        print()

    # Summary
    print("  " + "=" * (W - 2))
    print("  SUMMARY")
    print("  " + "-" * (W - 2))
    print(f"  Conditions evaluated  : {len(all_results)}")
    print(f"  Dimensions total      : {counts['total']}")
    print(f"  Evaluable             : {counts['evaluable']}")
    print(f"  PASS                  : {counts['pass']}")
    print(f"  FAIL                  : {counts['fail']}")
    print(f"  SUPPRESSED            : {counts['suppressed']}")
    print(f"  MISSING               : {counts['missing']}")
    print(f"  Overall readiness     : {health['readiness']}")

    if counts["suppressed"] == counts["total"]:
        print(
            "\n  All dimensions suppressed — physics warnings active."
            "\n  Calibrate heating rate (EXP-0001) before interpreting."
        )
    elif counts["fail"] == 0 and counts["suppressed"] == 0:
        print("\n  All dimensions within expected ranges. ✓")
    else:
        print(
            "\n  Start with Step 1 root cause."
            "\n  Run EXP-0001 to calibrate the heating rate."
            "\n  Re-run benchmark after each calibration step."
        )

    print("=" * W)


# ---------------------------------------------------------------------------
# Save results — full analysis preserved
# ---------------------------------------------------------------------------

def save_benchmark_results(
    benchmark: dict,
    all_results: list[dict],
    all_evaluations: list[dict],
    root_causes: list[dict],
    health: dict,
    counts: dict[str, int],
) -> Path:
    output = {
        "benchmark_schema_version":     "1.0",
        "benchmark_id":                 benchmark["benchmark_id"],
        "benchmark_status":             benchmark["status"],
        "benchmark_runner_version":     RUNNER_VERSION,
        "model_version":                "0.1.7",
        "timestamp":                    datetime.now(timezone.utc).isoformat(),
        "summary":                      counts,
        "physics_health":               health,
        "root_cause_analysis":          root_causes,
        "conditions":                   [],
    }

    for result, evaluation, condition in zip(
        all_results, all_evaluations, benchmark["conditions"]
    ):
        output["conditions"].append({
            "condition_id":          condition["condition_id"],
            "label":                 condition["label"],
            "pan_temp_c":            condition["pan_temperature_c"],
            "duration_min":          condition["duration_min"],
            "evaluation":            evaluation,
            "perception_confidence": result["perception"].get(
                "perceptual_confidence", "unknown"
            ),
            "physics_confidence":    result["perception"].get(
                "physics_confidence_score", 0.0
            ),
        })

    out_path = BENCH_DIR / "latest_benchmark_result.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()

    print("\n  Loading data...")

    ingredients = load_ingredients(DATA_DIR / "ingredients.json")
    recipes     = load_recipes(DATA_DIR / "recipes.json")
    parameters  = load_model_parameters(DATA_DIR / "model_parameters.json")
    recipe      = resolve_recipe("scrambled_eggs_basic", recipes, ingredients)

    benchmark_path = (
        Path(args.benchmark)
        if args.benchmark
        else BENCH_DIR / "expected_profile.json"
    )
    if not benchmark_path.exists():
        print(f"\n  ERROR: Benchmark file not found: {benchmark_path}")
        return 1

    benchmark = load_benchmark(benchmark_path)

    print(f"  Benchmark  : {benchmark['benchmark_id']}")
    print(f"  Conditions : {len(benchmark['conditions'])}")

    previous_path = Path(args.compare) if args.compare else None

    print("  Running simulations...")

    all_results:     list[dict] = []
    all_evaluations: list[dict] = []

    for condition in benchmark["conditions"]:
        result     = run_condition(condition, recipe, ingredients, parameters)
        evaluation = evaluate_condition(result, condition)
        all_results.append(result)
        all_evaluations.append(evaluation)

    root_causes = compute_root_cause_analysis(all_results, all_evaluations)
    health      = compute_physics_health(all_results, all_evaluations, root_causes)
    counts      = count_dimensions(all_evaluations)

    print_benchmark_report(
        benchmark,
        all_results,
        all_evaluations,
        root_causes,
        health,
        counts,
        show_evidence=args.show_evidence,
        verbose=args.verbose,
        previous_path=previous_path,
    )

    out_path = save_benchmark_results(
        benchmark,
        all_results,
        all_evaluations,
        root_causes,
        health,
        counts,
    )
    print(f"\n  Results saved to: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
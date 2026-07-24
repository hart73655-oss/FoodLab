"""
main.py
FoodLab v0.1.3

Runs a complete FoodLab simulation and saves the results.

Usage:
    python main.py
    python main.py --pan 150 --duration 4 --step 1.0
    python main.py --recipe scrambled_eggs_basic --no-save
    python main.py --full-json
    python main.py --output experiments/test1.json
    python C:\\Users\\minec\\OneDrive\\Desktop\\foodlab\\main.py
"""

import argparse
import json
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Project root — always absolute, works from any working directory
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR     = PROJECT_ROOT / "data"
RESULTS_DIR  = PROJECT_ROOT / "results"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.loader import (                                     # noqa: E402
    load_ingredients,
    load_model_parameters,
    load_recipes,
    resolve_recipe,
)
from engine.simulate import simulate                            # noqa: E402


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

VERSION = "0.1.3"


# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

DEFAULT_RECIPE_ID    = "scrambled_eggs_basic"
DEFAULT_PAN_TEMP_C   = 150.0
DEFAULT_DURATION_MIN = 4.0
DEFAULT_INITIAL_TEMP = 20.0
DEFAULT_TIME_STEP    = 1.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def safe_filename(value: str) -> str:
    """
    Removes characters that are invalid in Windows filenames.
    UUIDs are already safe, but future simulation IDs may not be.
    """
    invalid = '<>:"/\\|?*'
    return "".join(
        "_" if char in invalid else char
        for char in value
    )


def truncate(text: str, max_len: int = 50) -> str:
    """
    Truncates text only when it actually exceeds max_len.
    Avoids appending ... to text that is already short.
    """
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


def positive_float(value: str) -> float:
    """
    Argparse type validator.
    Rejects non-positive values before the simulation runs.
    """
    try:
        fval = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected a number, got: {value!r}"
        )
    if fval <= 0:
        raise argparse.ArgumentTypeError(
            f"must be greater than zero, got: {fval}"
        )
    return fval


def non_negative_float(value: str) -> float:
    """
    Argparse type validator.
    Rejects negative values before the simulation runs.
    """
    try:
        fval = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected a number, got: {value!r}"
        )
    if fval < 0:
        raise argparse.ArgumentTypeError(
            f"must be non-negative, got: {fval}"
        )
    return fval


def list_available_recipes(recipes: dict) -> str:
    """
    Returns a formatted string of available recipe IDs.
    Used in error messages when an unknown recipe is requested.
    """
    ids = sorted(recipes.keys())
    lines = ["  Available recipes:"]
    for rid in ids:
        lines.append(f"    - {rid}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"FoodLab Simulation Engine v{VERSION}",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--recipe",
        type=str,
        default=DEFAULT_RECIPE_ID,
        help="Recipe ID to simulate",
    )
    parser.add_argument(
        "--pan",
        type=positive_float,
        default=DEFAULT_PAN_TEMP_C,
        help="Pan temperature in Celsius (must be > 0)",
    )
    parser.add_argument(
        "--duration",
        type=non_negative_float,
        default=DEFAULT_DURATION_MIN,
        help="Cooking duration in minutes (must be >= 0)",
    )
    parser.add_argument(
        "--initial-temp",
        type=float,
        default=DEFAULT_INITIAL_TEMP,
        help="Initial food temperature in Celsius",
    )
    parser.add_argument(
        "--step",
        type=positive_float,
        default=DEFAULT_TIME_STEP,
        help="Simulation time step in seconds (must be > 0)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help=(
            "Custom output path for result JSON. "
            "Defaults to results/<simulation_id>.json"
        ),
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Print summary only. Do not save JSON to disk.",
    )
    parser.add_argument(
        "--full-json",
        action="store_true",
        help="Print full JSON output to terminal in addition to summary.",
    )
    parser.add_argument(
        "--list-recipes",
        action="store_true",
        help="List all available recipe IDs and exit.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Console summary
# ---------------------------------------------------------------------------

def print_summary(result: dict, elapsed_sec: float) -> None:
    out     = result["outputs"]
    initial = result["initial_state"]
    inputs  = result["inputs"]

    w_count  = len(result.get("warnings", []))
    dw_count = len(result.get("domain_warnings", []))
    pw_count = len(result.get("phase_warnings", []))
    total_w  = w_count + dw_count + pw_count

    print("\n" + "=" * 60)
    print(f"  FoodLab Simulation Summary  —  v{VERSION}")
    print("=" * 60)

    print(f"  Simulation ID  : {result['simulation_id']}")
    print(f"  Timestamp      : {result['timestamp']}")
    print(f"  Recipe         : {result['recipe_id']}")
    print(f"  Model version  : {result['model_version']}")
    print(f"  Exec time      : {elapsed_sec:.3f} s")

    print("\n  INPUTS")
    print("  " + "-" * 56)
    print(f"  Pan temperature  : {inputs['pan_temperature_c']} °C")
    print(f"  Duration         : {inputs['duration_min']} min")
    print(f"  Initial temp     : {inputs['initial_food_temperature_c']} °C")
    print(f"  Time step        : {inputs['time_step_sec']} s")

    print("\n  INITIAL STATE")
    print("  " + "-" * 56)
    print(f"  Total mass       : {initial['total_mass_g']} g")
    print(f"  Water mass       : {initial['water_mass_g']} g")

    print("\n  OUTPUTS")
    print("  " + "-" * 56)
    print(
        f"  Final temperature: "
        f"{out['estimated_final_temperature_c']} °C"
    )
    print(
        f"  Evap cooling     : "
        f"{out['cumulative_modeled_evaporative_temperature_reduction_c']} °C"
    )
    print(f"  Water loss       : {out['estimated_water_loss_g']} g")
    print(f"  Remaining water  : {out['remaining_water_mass_g']} g")
    print(f"  Final mass       : {out['estimated_final_mass_g']} g")
    print(f"  Butter melt      : {out['butter_melt_fraction'] * 100:.1f}%")
    print(
        f"  Protein denat.   : "
        f"{out['protein_denaturation_fraction'] * 100:.1f}%"
    )
    print(f"  Coagulation      : {out['coagulation_description']}")

    # Sensory report
    if "sensory_report" in result:
        sr   = result["sensory_report"]
        pc   = sr["physics_confidence"]
        dims = sr["dimensions"]
        ca   = sr.get("chef_assessment", {})

        print("\n  SENSORY REPORT")
        print("  " + "-" * 56)
        print(
            f"  Confidence       : {pc['label']} "
            f"(score {pc['score']:.2f})"
        )
        print(f"  Phase violation  : {sr['phase_violation_active']}")

        if pc.get("reason"):
            for r in pc["reason"]:
                print(f"    ↓ {r}")

        tex = dims["texture"]
        mst = dims["moisture"]
        app = dims.get("appearance", {})

        print(f"  Texture          : ", end="")
        if tex.get("score") is None:
            print("SUPPRESSED")
        else:
            print(tex["descriptor"])
            sd = tex.get("sub_dimensions", {})
            if sd:
                for name, val in sd.items():
                    print(f"    {name:<12}: {val['score']:.2f}")

        print(f"  Moisture         : ", end="")
        if mst.get("score") is None:
            print("SUPPRESSED")
        else:
            print(mst["descriptor"])

        print(f"  Richness         : {dims['richness']['descriptor']}")

        print(f"  Appearance       : ", end="")
        if app.get("score") is None and app.get("descriptor") == \
                dims["texture"].get("descriptor"):
            print("SUPPRESSED")
        elif app.get("color"):
            print(f"{app['color']}, {app['surface']}")
        else:
            print("SUPPRESSED")

        print(f"  Chef note        : {sr['chef_note']}")

        if ca.get("verdict"):
            print(f"  Verdict          : {ca['verdict']}")
        if ca.get("suitability"):
            print(f"  Suitability      : {ca['suitability']}")
        if ca.get("issues"):
            for issue in ca["issues"]:
                print(f"    ⚠ {issue}")

        print(
            f"  Status           : "
            f"{truncate(sr['interpretation_status'])}"
        )

    # Warnings — richer breakdown
    print(f"\n  WARNINGS")
    print("  " + "-" * 56)
    print(f"  Model            : {w_count}")
    print(f"  Domain           : {dw_count}")
    print(f"  Phase            : {pw_count}")
    print(f"  Total            : {total_w}")

    if total_w > 0:
        print()

    if result.get("phase_warnings"):
        for w in result["phase_warnings"]:
            print(
                f"  [PHASE/{w['severity'].upper()}]  "
                f"{w['code']}: {w['message']}"
            )

    if result.get("domain_warnings"):
        for w in result["domain_warnings"]:
            print(
                f"  [DOMAIN/{w['severity'].upper()}] "
                f"{w['code']}: {w['message']}"
            )

    if result.get("warnings"):
        for w in result["warnings"]:
            print(
                f"  [MODEL/{w['severity'].upper()}]  "
                f"{w['code']}: {w['message']}"
            )

    # Status
    print("\n  STATUS")
    print("  " + "-" * 56)
    print(f"  Domain status    : {result['domain_status']}")
    print(f"  Model status     : {result['model_status']}")
    print(f"  Validation       : {result['validation_status']}")

    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args  = parse_args()
    start = time.perf_counter()

    try:
        # Load data using absolute paths
        ingredients = load_ingredients(DATA_DIR / "ingredients.json")
        recipes     = load_recipes(DATA_DIR / "recipes.json")
        parameters  = load_model_parameters(
            DATA_DIR / "model_parameters.json"
        )

        # List recipes and exit if requested
        if args.list_recipes:
            print("\n  Available recipes:")
            for rid in sorted(recipes.keys()):
                print(f"    - {rid}")
            print()
            return 0

        # Validate recipe ID before running simulation
        if args.recipe not in recipes:
            print(f"\n  ERROR: Unknown recipe: {args.recipe!r}")
            print(list_available_recipes(recipes))
            return 1

        recipe = resolve_recipe(args.recipe, recipes, ingredients)

        # Run simulation
        result = simulate(
            recipe_id=args.recipe,
            recipe=recipe,
            ingredients=ingredients,
            parameters=parameters,
            pan_temperature_c=args.pan,
            duration_min=args.duration,
            initial_food_temp_c=args.initial_temp,
            time_step_sec=args.step,
        )

        elapsed = time.perf_counter() - start

        # Print full JSON if requested
        if args.full_json:
            print(json.dumps(result, indent=2))

        # Always print summary
        print_summary(result, elapsed)

        # Save result
        if not args.no_save:
            if args.output:
                output_file = Path(args.output)
                output_file.parent.mkdir(parents=True, exist_ok=True)
            else:
                RESULTS_DIR.mkdir(parents=True, exist_ok=True)
                filename    = f"{safe_filename(result['simulation_id'])}.json"
                output_file = RESULTS_DIR / filename

            with output_file.open("w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)

            print(f"\n  Saved to: {output_file}")

        return 0

    except FileNotFoundError as exc:
        print("\n  ERROR: Data file not found.")
        print(f"  {exc}")
        return 1

    except json.JSONDecodeError as exc:
        print("\n  ERROR: Invalid JSON in data file.")
        print(f"  {exc.msg}")
        print(f"  Line {exc.lineno}, column {exc.colno}")
        return 1

    except KeyError as exc:
        print("\n  ERROR: Missing key in data file.")
        print(f"  {exc}")
        return 1

    except RuntimeError as exc:
        print("\n  ERROR: Simulation invariant violated.")
        print(f"  {exc}")
        return 1

    except ValueError as exc:
        print("\n  ERROR: Invalid input value.")
        print(f"  {exc}")
        return 1

    except Exception as exc:
        print("\n  ERROR: Unexpected failure.")
        print(f"  {type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
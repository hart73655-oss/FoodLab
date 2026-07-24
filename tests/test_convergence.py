"""
tests/test_convergence.py

Numerical stability and convergence tests for the simulation engine.

Tests whether results converge as time step decreases,
whether physical invariants hold across all step sizes,
whether the simulation is idempotent,
and whether outputs are always finite.

This is not a unit test.
It is a numerical stability check.

Version: 0.1.2
"""

import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.loader import (
    load_ingredients,
    load_model_parameters,
    load_recipes,
    resolve_recipe,
)
from engine.simulate import simulate


# ---------------------------------------------------------------------------
# Tolerances
# ---------------------------------------------------------------------------

TEMP_REL_TOL   = 0.02   # 2% for temperature
LOSS_REL_TOL   = 0.05   # 5% for water loss
MASS_REL_TOL   = 0.001  # 0.1% for mass
ABS_TOL        = 1e-6   # absolute floor for near-zero values

STEP_SIZES = [2.0, 1.0, 0.5, 0.1]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def within_tolerance(
    a: float,
    b: float,
    rel_tol: float = 0.05,
    abs_tol: float = ABS_TOL,
) -> bool:
    """
    Returns True if a and b are close within rel_tol and abs_tol.
    Uses math.isclose for robust floating-point comparison.
    """
    return math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol)


def assert_finite_outputs(outputs: dict, label: str) -> None:
    """
    Raises AssertionError if any numeric output is NaN or infinite.
    Scientific simulations must never silently produce NaN or inf.
    """
    for key, value in outputs.items():
        if isinstance(value, (int, float)):
            assert math.isfinite(value), (
                f"{label}: output '{key}' is not finite. Got: {value}"
            )


def load_and_run(time_step_sec: float) -> dict:
    """
    Loads all data files and runs simulation with given time step.
    Reloads data every call to ensure no shared mutable state.
    """
    ingredients = load_ingredients("data/ingredients.json")
    recipes     = load_recipes("data/recipes.json")
    parameters  = load_model_parameters("data/model_parameters.json")
    recipe      = resolve_recipe(
        "scrambled_eggs_basic", recipes, ingredients
    )
    return simulate(
        recipe_id="scrambled_eggs_basic",
        recipe=recipe,
        ingredients=ingredients,
        parameters=parameters,
        pan_temperature_c=150.0,
        duration_min=4.0,
        initial_food_temp_c=20.0,
        time_step_sec=time_step_sec,
    )


def load_and_run_custom(
    pan_temperature_c: float,
    duration_min: float,
    initial_food_temp_c: float,
    time_step_sec: float,
) -> dict:
    """
    Loads all data files and runs simulation with custom parameters.
    """
    ingredients = load_ingredients("data/ingredients.json")
    recipes     = load_recipes("data/recipes.json")
    parameters  = load_model_parameters("data/model_parameters.json")
    recipe      = resolve_recipe(
        "scrambled_eggs_basic", recipes, ingredients
    )
    return simulate(
        recipe_id="scrambled_eggs_basic",
        recipe=recipe,
        ingredients=ingredients,
        parameters=parameters,
        pan_temperature_c=pan_temperature_c,
        duration_min=duration_min,
        initial_food_temp_c=initial_food_temp_c,
        time_step_sec=time_step_sec,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_finite_outputs() -> None:
    """
    All numeric outputs must be finite for every step size.
    NaN or inf indicates a numerical breakdown in the engine.
    """
    for dt in STEP_SIZES:
        result = load_and_run(dt)
        assert_finite_outputs(result["outputs"], label=f"dt={dt}")

    print("PASS  test_finite_outputs")


def test_idempotence() -> None:
    """
    Running the same simulation twice must produce identical results.
    Verifies there is no hidden mutable state or randomness.
    """
    r1 = load_and_run(1.0)
    r2 = load_and_run(1.0)

    assert r1["outputs"] == r2["outputs"], (
        "Idempotence violation: two identical runs produced "
        "different outputs.\n"
        f"Run 1: {r1['outputs']}\n"
        f"Run 2: {r2['outputs']}"
    )

    print("PASS  test_idempotence")


def test_convergence_table() -> None:
    """
    Prints a convergence table across all step sizes.
    Uses dt=0.1 as reference.
    Checks that dt=1.0 is within declared tolerances of dt=0.1.
    """
    results = {dt: load_and_run(dt) for dt in STEP_SIZES}
    ref     = results[0.1]["outputs"]

    print("\n--- Step-Size Convergence Table ---")
    print(
        f"{'Step':>8} | "
        f"{'Temp (°C)':>12} | "
        f"{'Water Loss (g)':>16} | "
        f"{'Final Mass (g)':>16} | "
        f"{'Cooling (°C)':>14}"
    )
    print("-" * 74)

    for dt in STEP_SIZES:
        out = results[dt]["outputs"]
        print(
            f"{dt:>8.1f} | "
            f"{out['estimated_final_temperature_c']:>12.4f} | "
            f"{out['estimated_water_loss_g']:>16.4f} | "
            f"{out['estimated_final_mass_g']:>16.4f} | "
            f"{out['cumulative_modeled_evaporative_temperature_reduction_c']:>14.4f}"
        )

    medium = results[1.0]["outputs"]

    temp_ok = within_tolerance(
        medium["estimated_final_temperature_c"],
        ref["estimated_final_temperature_c"],
        rel_tol=TEMP_REL_TOL,
    )
    loss_ok = within_tolerance(
        medium["estimated_water_loss_g"],
        ref["estimated_water_loss_g"],
        rel_tol=LOSS_REL_TOL,
    )
    mass_ok = within_tolerance(
        medium["estimated_final_mass_g"],
        ref["estimated_final_mass_g"],
        rel_tol=MASS_REL_TOL,
    )

    print("\n--- Convergence Check (dt=1.0 vs dt=0.1) ---")
    print(f"Temperature within {TEMP_REL_TOL*100:.0f}%: {temp_ok}")
    print(f"Water loss within  {LOSS_REL_TOL*100:.0f}%: {loss_ok}")
    print(f"Mass within        {MASS_REL_TOL*100:.1f}%: {mass_ok}")

    assert temp_ok, (
        f"Temperature not converged within {TEMP_REL_TOL*100:.0f}%. "
        f"dt=1.0 gives {medium['estimated_final_temperature_c']:.4f}, "
        f"dt=0.1 gives {ref['estimated_final_temperature_c']:.4f}"
    )
    assert loss_ok, (
        f"Water loss not converged within {LOSS_REL_TOL*100:.0f}%. "
        f"dt=1.0 gives {medium['estimated_water_loss_g']:.4f}, "
        f"dt=0.1 gives {ref['estimated_water_loss_g']:.4f}"
    )
    assert mass_ok, (
        f"Final mass not converged within {MASS_REL_TOL*100:.1f}%. "
        f"dt=1.0 gives {medium['estimated_final_mass_g']:.4f}, "
        f"dt=0.1 gives {ref['estimated_final_mass_g']:.4f}"
    )

    print("PASS  test_convergence_table")


def test_monotonic_convergence() -> None:
    """
    Errors relative to the finest step should decrease
    monotonically as step size decreases.

    Detects cases where results accidentally match at a coarse step
    but diverge at intermediate steps.

    Checks temperature, water loss, and final mass.
    """
    results = {dt: load_and_run(dt) for dt in STEP_SIZES}
    ref     = results[0.1]["outputs"]

    def rel_error(value: float, reference: float) -> float:
        if reference == 0.0:
            return abs(value)
        return abs(value - reference) / abs(reference)

    keys = [
        "estimated_final_temperature_c",
        "estimated_water_loss_g",
        "estimated_final_mass_g",
    ]

    print("\n--- Monotonic Convergence Check ---")

    for key in keys:
        errors = {
            dt: rel_error(results[dt]["outputs"][key], ref[key])
            for dt in STEP_SIZES
        }

        print(f"\n  {key}")
        for dt in STEP_SIZES:
            print(f"    dt={dt:.1f}  error={errors[dt]:.6f}")

        # Check each consecutive pair
        sorted_steps = sorted(STEP_SIZES, reverse=True)
        for i in range(len(sorted_steps) - 1):
            coarse = sorted_steps[i]
            fine   = sorted_steps[i + 1]

            # Allow a small margin for floating-point noise
            assert errors[coarse] >= errors[fine] - 1e-6, (
                f"Non-monotonic convergence for '{key}': "
                f"error at dt={coarse} ({errors[coarse]:.6f}) "
                f"is less than error at dt={fine} ({errors[fine]:.6f}). "
                f"Results are not converging smoothly."
            )

    print("\nPASS  test_monotonic_convergence")


def test_invariants_across_step_sizes() -> None:
    """
    Physical invariants must hold for every step size.
    These are not convergence checks.
    They verify the engine never violates basic physics.
    """
    for dt in STEP_SIZES:
        result  = load_and_run(dt)
        outputs = result["outputs"]
        initial = result["initial_state"]

        assert outputs["estimated_final_mass_g"] >= 0.0, (
            f"dt={dt}: final mass became negative"
        )
        assert outputs["estimated_final_mass_g"] <= initial["total_mass_g"], (
            f"dt={dt}: final mass exceeds initial mass"
        )
        assert outputs["estimated_water_loss_g"] <= initial["water_mass_g"], (
            f"dt={dt}: water loss exceeds initial water"
        )
        assert outputs["cumulative_modeled_evaporative_temperature_reduction_c"] >= 0.0, (
            f"dt={dt}: evaporation cooling became negative"
        )

        # Mass conservation
        expected_final = (
            initial["total_mass_g"]
            - outputs["estimated_water_loss_g"]
        )
        assert math.isclose(
            expected_final,
            outputs["estimated_final_mass_g"],
            abs_tol=1e-3,
        ), (
            f"dt={dt}: mass conservation violated. "
            f"Expected {expected_final:.4f}, "
            f"got {outputs['estimated_final_mass_g']:.4f}"
        )

    print("PASS  test_invariants_across_step_sizes")


def test_cooling_sanity() -> None:
    """
    Cumulative evaporative cooling must not exceed
    the final food temperature itself.

    A runaway cooling bug would produce more cooling
    than the food ever had temperature above zero.
    """
    for dt in STEP_SIZES:
        result  = load_and_run(dt)
        outputs = result["outputs"]

        cooling = outputs[
            "cumulative_modeled_evaporative_temperature_reduction_c"
        ]
        final_temp = outputs["estimated_final_temperature_c"]

        assert cooling <= final_temp + 1e-6, (
            f"dt={dt}: cumulative cooling ({cooling:.4f}°C) "
            f"exceeds final temperature ({final_temp:.4f}°C). "
            f"Possible runaway cooling bug."
        )
        assert cooling >= 0.0, (
            f"dt={dt}: cumulative cooling is negative ({cooling:.4f}°C)."
        )

    print("PASS  test_cooling_sanity")


def test_zero_water_loss_below_threshold() -> None:
    """
    When pan temperature is 50°C, food never reaches 60°C.
    Water loss must be exactly zero.
    """
    result = load_and_run_custom(
        pan_temperature_c=50.0,
        duration_min=4.0,
        initial_food_temp_c=20.0,
        time_step_sec=1.0,
    )

    assert result["outputs"]["estimated_water_loss_g"] == 0.0, (
        "Water loss should be zero when food temperature "
        "never reaches 60°C evaporation threshold. "
        f"Got: {result['outputs']['estimated_water_loss_g']}"
    )

    print("PASS  test_zero_water_loss_below_threshold")


def test_zero_duration_preserves_state() -> None:
    """
    Zero duration must preserve the initial state exactly.
    No mass change, no temperature change, no water loss.
    """
    result  = load_and_run_custom(
        pan_temperature_c=150.0,
        duration_min=0.0,
        initial_food_temp_c=20.0,
        time_step_sec=1.0,
    )
    outputs = result["outputs"]
    initial = result["initial_state"]

    assert outputs["estimated_water_loss_g"] == 0.0, (
        f"Zero duration should produce zero water loss. "
        f"Got: {outputs['estimated_water_loss_g']}"
    )
    assert math.isclose(
        outputs["estimated_final_mass_g"],
        initial["total_mass_g"],
        abs_tol=1e-6,
    ), (
        f"Zero duration should preserve mass. "
        f"Expected {initial['total_mass_g']}, "
        f"got {outputs['estimated_final_mass_g']}"
    )
    assert math.isclose(
        outputs["estimated_final_temperature_c"],
        20.0,
        abs_tol=1e-6,
    ), (
        f"Zero duration should preserve initial temperature. "
        f"Got: {outputs['estimated_final_temperature_c']}"
    )

    print("PASS  test_zero_duration_preserves_state")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("FoodLab Convergence and Stability Tests  v0.1.2")
    print("=" * 60)

    test_finite_outputs()
    test_idempotence()
    test_convergence_table()
    test_monotonic_convergence()
    test_invariants_across_step_sizes()
    test_cooling_sanity()
    test_zero_water_loss_below_threshold()
    test_zero_duration_preserves_state()

    print("\n" + "=" * 60)
    print("All tests passed.")
    print("=" * 60)
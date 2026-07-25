"""
tests/unit/test_invariants.py
FoodLab v0.1.7

Verifies physical invariants hold across the complete
simulation timeline, not only the final output.

Test categories:
  1.  Final state bounds (mass, water, temperature)
  2.  History bounds (every step, not just final)
  3.  Fraction bounds (all tracked fractions)
  4.  Irreversibility (browning, denaturation, exposure)
  5.  History length and timing
  6.  History chronology (timestamps always advance)
  7.  History step size (never exceeds requested dt)
  8.  Mass balance across history
  9.  Zero-duration behavior
  10. Determinism (outputs, history, events, warnings)
  11. Event presence, structure, and chronology
  12. Event ID uniqueness
  13. Temperature boundary (heating and cooling)
  14. Output schema regression protection
"""

import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR     = PROJECT_ROOT / "data"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.loader import (
    load_ingredients,
    load_model_parameters,
    load_recipes,
    resolve_recipe,
)
from engine.simulate import simulate
from engine.state import TimeStep


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_result(
    pan: float          = 150.0,
    duration: float     = 4.0,
    time_step: float    = 1.0,
    initial_temp: float = 20.0,
) -> dict:
    """
    Loads data files using absolute paths and runs simulation.
    Returns a JSON-serialisable dict.
    """
    ingredients = load_ingredients(DATA_DIR / "ingredients.json")
    recipes     = load_recipes(DATA_DIR / "recipes.json")
    parameters  = load_model_parameters(DATA_DIR / "model_parameters.json")
    recipe      = resolve_recipe(
        "scrambled_eggs_basic", recipes, ingredients
    )
    return simulate(
        recipe_id="scrambled_eggs_basic",
        recipe=recipe,
        ingredients=ingredients,
        parameters=parameters,
        pan_temperature_c=pan,
        duration_min=duration,
        initial_food_temp_c=initial_temp,
        time_step_sec=time_step,
    )


def get_history(result: dict) -> list[TimeStep]:
    """
    Reconstructs TimeStep objects from history dicts.
    Explicitly passes only the fields TimeStep expects.
    """
    steps = []
    for step_dict in result.get("history", []):
        steps.append(TimeStep(
            elapsed_sec=              step_dict["elapsed_sec"],
            food_temp_c=              step_dict["food_temp_c"],
            effective_surface_temp_c= step_dict["effective_surface_temp_c"],
            water_mass_g=             step_dict["water_mass_g"],
            total_mass_g=             step_dict["total_mass_g"],
            butter_melt_fraction=     step_dict["butter_melt_fraction"],
            protein_denaturation=     step_dict["protein_denaturation"],
            browning_index=           step_dict["browning_index"],
            burn_index=               step_dict["burn_index"],
            stickiness_index=         step_dict["stickiness_index"],
            evap_cooling_c=           step_dict["evap_cooling_c"],
            high_temp_exposure_sec=   step_dict["high_temp_exposure_sec"],
        ))
    return steps


# ---------------------------------------------------------------------------
# 1. Final state bounds
# ---------------------------------------------------------------------------

def test_mass_never_increases():
    result  = get_result()
    initial = result["initial_state"]["total_mass_g"]
    final   = result["outputs"]["estimated_final_mass_g"]
    assert final <= initial + 1e-6, (
        f"Final mass {final} exceeds initial {initial}"
    )


def test_mass_never_negative():
    result = get_result()
    assert result["outputs"]["estimated_final_mass_g"] >= 0.0


def test_water_loss_within_initial_water():
    result        = get_result()
    initial_water = result["initial_state"]["water_mass_g"]
    water_loss    = result["outputs"]["estimated_water_loss_g"]
    assert water_loss <= initial_water + 1e-6, (
        f"Water loss {water_loss} exceeds initial water {initial_water}"
    )


def test_temperature_does_not_exceed_pan():
    result  = get_result(pan=150.0)
    final_t = result["outputs"]["estimated_final_temperature_c"]
    assert final_t <= 150.0 + 1e-6, (
        f"Food temp {final_t} exceeded pan temp 150.0"
    )


# ---------------------------------------------------------------------------
# 2. History bounds — every step
# ---------------------------------------------------------------------------

def test_history_mass_and_water_bounds():
    result        = get_result()
    history       = get_history(result)
    initial_water = result["initial_state"]["water_mass_g"]

    for step in history:
        assert step.total_mass_g >= -1e-6, (
            f"total_mass_g negative at {step.elapsed_sec}s: {step.total_mass_g}"
        )
        assert step.water_mass_g >= -1e-6, (
            f"water_mass_g negative at {step.elapsed_sec}s: {step.water_mass_g}"
        )
        assert step.water_mass_g <= initial_water + 1e-6, (
            f"water_mass_g exceeded initial at {step.elapsed_sec}s: "
            f"{step.water_mass_g} > {initial_water}"
        )
        assert step.water_mass_g <= step.total_mass_g + 1e-6, (
            f"water_mass_g exceeded total_mass_g at {step.elapsed_sec}s: "
            f"{step.water_mass_g} > {step.total_mass_g}"
        )


def test_history_total_mass_is_nonincreasing():
    """
    Total mass must never increase between steps.
    Evaporation removes mass so this tests that no mass
    is being created during the simulation.
    Note: this is not strict conservation. It only checks direction.
    See test_mass_balance_across_history for full conservation.
    """
    result  = get_result()
    history = get_history(result)
    for i in range(1, len(history)):
        assert history[i].total_mass_g <= history[i - 1].total_mass_g + 1e-6, (
            f"Mass increased at step {i}: "
            f"{history[i].total_mass_g} > {history[i-1].total_mass_g}"
        )


# ---------------------------------------------------------------------------
# 3. Fraction bounds — all tracked fractions
# ---------------------------------------------------------------------------

def test_all_fractions_within_bounds():
    """
    All model fractions must stay within [0.0, 1.0] at every step.
    """
    result  = get_result()
    history = get_history(result)

    for step in history:
        fractions = {
            "butter_melt_fraction": step.butter_melt_fraction,
            "protein_denaturation": step.protein_denaturation,
            "browning_index":       step.browning_index,
            "burn_index":           step.burn_index,
            "stickiness_index":     step.stickiness_index,
        }
        for name, value in fractions.items():
            assert 0.0 - 1e-6 <= value <= 1.0 + 1e-6, (
                f"{name} out of bounds at {step.elapsed_sec}s: {value}"
            )


# ---------------------------------------------------------------------------
# 4. Irreversibility
# ---------------------------------------------------------------------------

def test_irreversible_states_never_decrease():
    """
    Browning, protein denaturation, and cumulative high-temp exposure
    are declared irreversible. They must never decrease.

    Stickiness and burn index are NOT tested here:
      - Stickiness is an instantaneous tendency.
      - Burn index depends on instantaneous conditions.
    """
    history = get_history(get_result())

    for previous, current in zip(history, history[1:]):
        assert current.protein_denaturation >= previous.protein_denaturation - 1e-9, (
            f"protein_denaturation decreased at {current.elapsed_sec}s: "
            f"{current.protein_denaturation} < {previous.protein_denaturation}"
        )
        assert current.browning_index >= previous.browning_index - 1e-9, (
            f"browning_index decreased at {current.elapsed_sec}s: "
            f"{current.browning_index} < {previous.browning_index}"
        )
        assert current.high_temp_exposure_sec >= previous.high_temp_exposure_sec - 1e-9, (
            f"high_temp_exposure_sec decreased at {current.elapsed_sec}s: "
            f"{current.high_temp_exposure_sec} < {previous.high_temp_exposure_sec}"
        )


# ---------------------------------------------------------------------------
# 5. History length and timing
# ---------------------------------------------------------------------------

def test_history_length_matches_duration():
    result  = get_result(duration=4.0, time_step=1.0)
    history = result["history"]
    assert len(history) == 240, (
        f"Expected 240 steps for 4 min at 1s step, got {len(history)}"
    )


def test_history_length_with_partial_final_step():
    """
    When duration is not exactly divisible by time_step,
    the loop must still reach exactly the end of the duration.

    Expected steps = ceil(duration_sec / time_step_sec)
    Final elapsed time must equal duration_sec exactly.
    """
    duration_min = 1.01
    time_step    = 7.0
    duration_sec = duration_min * 60.0

    result   = get_result(duration=duration_min, time_step=time_step)
    history  = result["history"]
    expected = math.ceil(duration_sec / time_step)

    assert len(history) == expected, (
        f"Expected {expected} steps for {duration_min} min "
        f"at {time_step}s step, got {len(history)}"
    )

    final_elapsed = history[-1]["elapsed_sec"]
    assert abs(final_elapsed - duration_sec) < 0.01, (
        f"Final elapsed time {final_elapsed}s does not match "
        f"expected {duration_sec}s"
    )


# ---------------------------------------------------------------------------
# 6. History chronology
# ---------------------------------------------------------------------------

def test_history_times_strictly_increase():
    """
    Every history timestamp must be strictly greater than the previous.
    """
    history = get_result()["history"]

    for previous, current in zip(history, history[1:]):
        assert current["elapsed_sec"] > previous["elapsed_sec"], (
            f"History time did not advance: "
            f"{previous['elapsed_sec']} -> {current['elapsed_sec']}"
        )


# ---------------------------------------------------------------------------
# 7. History step sizes
# ---------------------------------------------------------------------------

def test_history_step_sizes_do_not_exceed_requested_dt():
    """
    No step interval in the history should exceed the requested time_step.
    The final step may be shorter (partial step).
    """
    time_step = 7.0
    history   = get_result(duration=1.01, time_step=time_step)["history"]

    previous_time = 0.0
    for step in history:
        dt = step["elapsed_sec"] - previous_time
        assert 0.0 < dt <= time_step + 1e-9, (
            f"Step size {dt:.4f}s exceeds requested time_step {time_step}s"
        )
        previous_time = step["elapsed_sec"]


# ---------------------------------------------------------------------------
# 8. Mass balance across history
# ---------------------------------------------------------------------------

def test_mass_balance_across_history():
    """
    At every step:
        initial_mass == current_mixture_mass + water_lost_so_far

    Water lost so far = initial_mass - current total_mass.
    This checks strict mass conservation across the timeline.
    """
    result       = get_result()
    history      = result["history"]
    initial_mass = result["initial_state"]["total_mass_g"]

    for step in history:
        water_lost_so_far = initial_mass - step["total_mass_g"]

        assert water_lost_so_far >= -1e-6, (
            f"Negative water loss implied at {step['elapsed_sec']}s: "
            f"{water_lost_so_far}"
        )
        reconstructed = step["total_mass_g"] + water_lost_so_far
        assert abs(reconstructed - initial_mass) <= 1e-6, (
            f"Mass balance violated at {step['elapsed_sec']}s: "
            f"total={step['total_mass_g']}, "
            f"lost={water_lost_so_far}, "
            f"sum={reconstructed}, "
            f"expected={initial_mass}"
        )


# ---------------------------------------------------------------------------
# 9. Zero-duration behavior
# ---------------------------------------------------------------------------

def test_zero_duration_no_change():
    """
    Zero-duration simulation must produce no changes.
    History must be empty.
    All accumulating quantities must be zero.

    Note: butter_melt_fraction and protein_denaturation may be
    non-zero at t=0 if initial temperature is above their thresholds.
    They are not checked here for that reason.
    """
    result = get_result(duration=0.0, initial_temp=20.0)
    out    = result["outputs"]

    assert result["history"] == [], (
        "Zero-duration simulation should produce empty history"
    )
    assert abs(out["estimated_final_temperature_c"] - 20.0) < 1e-6, (
        f"Temperature changed during zero-duration run: "
        f"{out['estimated_final_temperature_c']}"
    )
    assert out["estimated_water_loss_g"]            == 0.0
    assert out["browning_index"]                    == 0.0
    assert out["burn_index"]                        == 0.0
    assert out["cumulative_high_temp_exposure_sec"] == 0.0
    assert abs(
        out["estimated_final_mass_g"]
        - result["initial_state"]["total_mass_g"]
    ) < 1e-6


# ---------------------------------------------------------------------------
# 10. Determinism
# ---------------------------------------------------------------------------

def test_deterministic():
    """
    Two identical runs must produce identical outputs, history, events,
    and warnings. UUIDs, timestamps, and metadata are not compared.
    """
    r1 = get_result()
    r2 = get_result()

    assert r1["outputs"]        == r2["outputs"],        "Outputs differ"
    assert r1["history"]        == r2["history"],        "History differs"
    assert r1["events"]         == r2["events"],         "Events differ"
    assert r1["warnings"]       == r2["warnings"],       "Warnings differ"
    assert r1["domain_warnings"] == r2["domain_warnings"], "Domain warnings differ"
    assert r1["phase_warnings"]  == r2["phase_warnings"],  "Phase warnings differ"
    assert r1["sensory_report"]  == r2["sensory_report"],  "Sensory reports differ"


# ---------------------------------------------------------------------------
# 11. Event presence, structure, and chronology
# ---------------------------------------------------------------------------

def test_events_structure():
    """
    Events must be a non-empty list for a standard run.
    Each event must contain all required keys.
    """
    result = get_result()
    events = result.get("events", [])

    assert isinstance(events, list), "events field must be a list"
    assert len(events) > 0, (
        "Expected at least one event for standard 4-minute simulation. "
        "Check that detect_events is called and result.events is populated."
    )

    required_keys = {
        "event_id", "elapsed_sec", "description",
        "field", "threshold", "observed_value", "severity",
    }
    for event in events:
        missing = required_keys - set(event.keys())
        assert not missing, (
            f"Event missing keys: {missing}. Event: {event}"
        )


def test_events_are_within_simulation_duration():
    """
    Every event must occur within the simulation time window.
    """
    result       = get_result()
    duration_sec = result["inputs"]["duration_min"] * 60.0

    for event in result["events"]:
        assert 0.0 <= event["elapsed_sec"] <= duration_sec + 1e-6, (
            f"Event {event['event_id']} at {event['elapsed_sec']}s "
            f"is outside simulation duration {duration_sec}s"
        )


def test_events_are_chronological():
    """
    Events must be returned in ascending time order.
    """
    events = get_result()["events"]
    times  = [event["elapsed_sec"] for event in events]
    assert times == sorted(times), (
        f"Events are not in chronological order: {times}"
    )


# ---------------------------------------------------------------------------
# 12. Event ID uniqueness
# ---------------------------------------------------------------------------

def test_event_ids_are_unique():
    """
    Each event_id should appear at most once.
    Events are one-shot: they fire when a threshold is first crossed.
    """
    events = get_result()["events"]
    ids    = [event["event_id"] for event in events]
    assert len(ids) == len(set(ids)), (
        f"Duplicate event IDs detected: "
        f"{[x for x in ids if ids.count(x) > 1]}"
    )


# ---------------------------------------------------------------------------
# 13. Temperature boundary — heating and cooling
# ---------------------------------------------------------------------------

def test_temperature_remains_between_thermal_boundaries_heating():
    """
    When pan is hotter than initial food temperature,
    food temperature must stay between initial and pan at every step.
    """
    initial_temp = 20.0
    pan_temp     = 150.0
    low          = initial_temp - 1e-6
    high         = pan_temp     + 1e-6

    result  = get_result(pan=pan_temp, initial_temp=initial_temp)
    history = get_history(result)

    for step in history:
        assert low <= step.food_temp_c <= high, (
            f"food_temp_c {step.food_temp_c} outside "
            f"[{low:.1f}, {high:.1f}] at {step.elapsed_sec}s"
        )


def test_temperature_remains_between_thermal_boundaries_cooling():
    """
    When pan is cooler than initial food temperature (cooling case),
    food temperature must stay between pan and initial at every step.
    """
    initial_temp = 80.0
    pan_temp     = 20.0
    low          = pan_temp     - 1e-6
    high         = initial_temp + 1e-6

    result  = get_result(pan=pan_temp, initial_temp=initial_temp)
    history = get_history(result)

    for step in history:
        assert low <= step.food_temp_c <= high, (
            f"food_temp_c {step.food_temp_c} outside "
            f"[{low:.1f}, {high:.1f}] at {step.elapsed_sec}s"
        )


# ---------------------------------------------------------------------------
# 14. Output schema regression protection
# ---------------------------------------------------------------------------

def test_required_output_keys_present():
    result = get_result()
    out    = result["outputs"]

    required = {
        "estimated_final_temperature_c",
        "effective_surface_temperature_c",
        "cumulative_modeled_evaporative_temperature_reduction_c",
        "butter_melt_fraction",
        "protein_denaturation_fraction",
        "coagulation_description",
        "estimated_water_loss_g",
        "remaining_water_mass_g",
        "estimated_final_mass_g",
        "browning_index",
        "browning_description",
        "browning_bar",
        "burn_index",
        "burn_risk",
        "burn_bar",
        "stickiness_index",
        "stickiness_description",
        "stickiness_bar",
        "cumulative_high_temp_exposure_sec",
    }

    missing = required - set(out.keys())
    assert not missing, f"Missing output keys: {missing}"


def test_required_top_level_keys_present():
    result = get_result()

    required = {
        "simulation_id",
        "timestamp",
        "recipe_id",
        "model_version",
        "inputs",
        "initial_state",
        "outputs",
        "warnings",
        "domain_warnings",
        "phase_warnings",
        "assumptions",
        "sensory_report",
        "events",
        "metadata",
        "history",
    }

    missing = required - set(result.keys())
    assert not missing, f"Missing top-level keys: {missing}"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        # 1. Final state bounds
        test_mass_never_increases,
        test_mass_never_negative,
        test_water_loss_within_initial_water,
        test_temperature_does_not_exceed_pan,

        # 2. History bounds
        test_history_mass_and_water_bounds,
        test_history_total_mass_is_nonincreasing,

        # 3. Fraction bounds
        test_all_fractions_within_bounds,

        # 4. Irreversibility
        test_irreversible_states_never_decrease,

        # 5. History length and timing
        test_history_length_matches_duration,
        test_history_length_with_partial_final_step,

        # 6. History chronology
        test_history_times_strictly_increase,

        # 7. History step sizes
        test_history_step_sizes_do_not_exceed_requested_dt,

        # 8. Mass balance
        test_mass_balance_across_history,

        # 9. Zero duration
        test_zero_duration_no_change,

        # 10. Determinism
        test_deterministic,

        # 11. Events
        test_events_structure,
        test_events_are_within_simulation_duration,
        test_events_are_chronological,

        # 12. Event uniqueness
        test_event_ids_are_unique,

        # 13. Temperature boundary
        test_temperature_remains_between_thermal_boundaries_heating,
        test_temperature_remains_between_thermal_boundaries_cooling,

        # 14. Schema regression
        test_required_output_keys_present,
        test_required_top_level_keys_present,
    ]

    passed = 0
    failed = 0

    print("\nFoodLab Invariant Tests  v0.1.7")
    print("=" * 55)

    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except AssertionError as exc:
            print(f"  FAIL  {test.__name__}")
            print(f"        {exc}")
            failed += 1
        except Exception as exc:
            print(f"  ERROR {test.__name__}: {type(exc).__name__}: {exc}")
            failed += 1

    print("=" * 55)
    print(f"  {passed} passed  {failed} failed")

    if failed > 0:
        raise SystemExit(1)
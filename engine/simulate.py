"""
simulate.py
Orchestrates the V0.1.3 simulation pipeline.

Pipeline order:
  1. Validate simulation inputs
  2. Load and validate model parameters
  3. Build initial mixture state
  4. Run time-step loop:
       a. Estimate mixture temperature from heating model
       b. Apply cumulative evaporation cooling
       c. Calculate butter melting
       d. Calculate protein denaturation (irreversibility enforced)
       e. Calculate water evaporation
       f. Calculate evaporation cooling feedback
  5. Check physical invariants
  6. Check phase warnings
  7. Generate sensory report
  8. Produce structured output with all warnings

Changes from v0.1.2:
  - uuid and datetime imports added
  - simulation_id is now a unique UUID per run
  - timestamp added to output
  - model_version bumped to 0.1.3
  - Sensory report integrated via models.sensory
  - sensory_report added to output dict
  - Sensory assumptions A-SE-001 to A-SE-005 added
"""

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from models import (                                            # noqa: E402
    butter_melting,
    mixture_heating,
    protein_denaturation,
    sensory,
    water_evaporation,
)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def _validate_inputs(
    pan_temperature_c: float,
    duration_min: float,
    initial_food_temp_c: float,
    time_step_sec: float,
) -> None:
    if time_step_sec <= 0:
        raise ValueError(
            f"time_step_sec must be greater than zero. "
            f"Got: {time_step_sec}"
        )
    if duration_min < 0:
        raise ValueError(
            f"duration_min must be non-negative. "
            f"Got: {duration_min}"
        )
    if pan_temperature_c <= 0:
        raise ValueError(
            f"pan_temperature_c must be greater than zero. "
            f"Got: {pan_temperature_c}"
        )
    if initial_food_temp_c < -273.15:
        raise ValueError(
            f"initial_food_temp_c is below absolute zero. "
            f"Got: {initial_food_temp_c}"
        )


# ---------------------------------------------------------------------------
# Physical invariants
# ---------------------------------------------------------------------------

def _check_invariants(
    estimated_final_mass_g: float,
    initial_total_mass_g: float,
    estimated_water_loss_g: float,
    initial_water_mass_g: float,
    current_temp: float,
    initial_food_temp_c: float,
    pan_temperature_c: float,
) -> None:
    if estimated_final_mass_g < 0.0:
        raise RuntimeError(
            "Invariant violation: final mass became negative."
        )
    if estimated_final_mass_g > initial_total_mass_g:
        raise RuntimeError(
            "Invariant violation: final mass exceeds initial mass."
        )
    if estimated_water_loss_g > initial_water_mass_g:
        raise RuntimeError(
            "Invariant violation: water loss exceeds initial water mass."
        )
    upper_bound = max(initial_food_temp_c, pan_temperature_c)
    if current_temp > upper_bound:
        raise RuntimeError(
            f"Invariant violation: food temperature {current_temp} "
            f"exceeded the hotter boundary temperature {upper_bound}."
        )


# ---------------------------------------------------------------------------
# Phase warnings
# ---------------------------------------------------------------------------

def _check_phase_warnings(
    current_temp: float,
    current_water_mass_g: float,
    initial_water_mass_g: float,
) -> list[dict]:
    """
    Checks for physically suspicious temperature and water combinations.
    Does not clamp temperature.
    Returns warnings instead of modifying state.
    """
    phase_warnings = []

    water_fraction_remaining = (
        current_water_mass_g / initial_water_mass_g
        if initial_water_mass_g > 0.0
        else 0.0
    )

    if current_temp > 100.0 and water_fraction_remaining > 0.1:
        phase_warnings.append({
            "code": "W-PHASE-001",
            "severity": "high",
            "model": "water_evaporation_v0.1",
            "mixture_temperature_c": round(current_temp, 2),
            "water_fraction_remaining": round(water_fraction_remaining, 3),
            "message": (
                "Modeled mixture temperature exceeds the boiling region "
                "while substantial water remains."
            ),
            "consequence": (
                "The current model does not represent boiling, "
                "vigorous evaporation, pressure effects, or "
                "phase-equilibrium temperature limits. "
                "Results above 100°C with significant water present "
                "are not physically realistic."
            ),
        })

    return phase_warnings


# ---------------------------------------------------------------------------
# Initial state builder
# ---------------------------------------------------------------------------

def build_initial_state(
    recipe: dict,
    ingredients: dict,
) -> dict:
    """
    Calculates initial mixture mass and composition
    from recipe quantities and ingredient fractions.

    Returns
    -------
    dict with keys:
        total_mass_g
        water_mass_g
        protein_mass_g
        fat_mass_g
    """
    total_mass_g    = 0.0
    total_water_g   = 0.0
    total_protein_g = 0.0
    total_fat_g     = 0.0

    for ing_id, ing_recipe in recipe["ingredients"].items():
        mass = ing_recipe["amount_g"]
        total_mass_g += mass

        comp = ingredients[ing_id].get("composition", {})

        water_frac = comp.get(
            "water_mass_fraction", {}
        ).get("value", 0.0)
        protein_frac = comp.get(
            "protein_mass_fraction", {}
        ).get("value", 0.0)
        fat_frac = comp.get(
            "fat_mass_fraction", {}
        ).get("value", 0.0)

        total_water_g   += mass * water_frac
        total_protein_g += mass * protein_frac
        total_fat_g     += mass * fat_frac

    return {
        "total_mass_g":   total_mass_g,
        "water_mass_g":   total_water_g,
        "protein_mass_g": total_protein_g,
        "fat_mass_g":     total_fat_g,
    }


# ---------------------------------------------------------------------------
# Main simulation function
# ---------------------------------------------------------------------------

def simulate(
    recipe_id: str,
    recipe: dict,
    ingredients: dict,
    parameters: dict,
    pan_temperature_c: float,
    duration_min: float,
    initial_food_temp_c: float = 20.0,
    time_step_sec: float = 1.0,
) -> dict:
    """
    Runs the V0.1.3 simulation pipeline.

    Returns a structured result dict including outputs,
    sensory report, warnings, phase warnings,
    domain status, and active assumptions.
    """

    warnings_list   = []
    domain_warnings = []

    # --- 1. Validate inputs ---
    _validate_inputs(
        pan_temperature_c=pan_temperature_c,
        duration_min=duration_min,
        initial_food_temp_c=initial_food_temp_c,
        time_step_sec=time_step_sec,
    )

    # --- 2. Load model parameters ---
    heating_params = parameters["mixture_heating_v0.1"]
    melt_params    = parameters["butter_melting_v0.1"]
    denat_params   = parameters["whole_egg_denaturation_v0.1"]
    evap_params    = parameters["water_evaporation_v0.1"]

    heating_rate = heating_params["heating_rate_per_second"]["value"]
    evap_rate    = evap_params[
        "evaporation_rate_g_per_sec_per_celsius"
    ]["value"]

    if heating_params[
        "heating_rate_per_second"
    ]["status"] == "unfitted_placeholder":
        warnings_list.append({
            "code": "W-001",
            "severity": "high",
            "model": "mixture_heating_v0.1",
            "message": (
                "Heating-rate parameter is an unfitted placeholder."
            ),
            "consequence": (
                "Temperature and all dependent outputs "
                "are not validated."
            ),
        })

    if evap_params[
        "evaporation_rate_g_per_sec_per_celsius"
    ]["status"] == "unfitted_placeholder":
        warnings_list.append({
            "code": "W-003",
            "severity": "high",
            "model": "water_evaporation_v0.1",
            "message": (
                "Evaporation-rate parameter is an "
                "unfitted placeholder."
            ),
            "consequence": (
                "Water loss estimate is not validated."
            ),
        })

    # --- 3. Build initial mixture state ---
    initial_state        = build_initial_state(recipe, ingredients)
    initial_total_mass_g = initial_state["total_mass_g"]
    initial_water_mass_g = initial_state["water_mass_g"]

    current_water_mass_g = initial_water_mass_g
    current_total_mass_g = initial_total_mass_g
    total_water_loss_g   = 0.0

    # --- 4. Domain check for heating model ---
    domain_warnings += mixture_heating.check_domain(
        initial_temp_c=initial_food_temp_c,
        pan_temp_c=pan_temperature_c,
        elapsed_sec=duration_min * 60.0,
    )

    # --- 5. Calculate initial fractions at t=0 ---
    initial_denaturation = protein_denaturation.denaturation_fraction(
        food_temp_c=initial_food_temp_c,
        start_temp_c=denat_params["start_temperature_c"]["value"],
        complete_temp_c=denat_params["complete_temperature_c"]["value"],
    )

    final_butter_melt = butter_melting.butter_melt_fraction(
        food_temp_c=initial_food_temp_c,
        melt_start_c=melt_params["start_temperature_c"]["value"],
        melt_complete_c=melt_params["complete_temperature_c"]["value"],
    )

    final_denaturation   = initial_denaturation
    current_temp         = float(initial_food_temp_c)
    cumulative_cooling_c = 0.0

    # --- 6. Time-step simulation loop ---
    duration_sec = duration_min * 60.0
    elapsed      = 0.0

    while elapsed < duration_sec:
        elapsed = min(elapsed + time_step_sec, duration_sec)

        # a. Temperature from heating model
        heated_temp = mixture_heating.estimate_food_temperature(
            initial_temp_c=initial_food_temp_c,
            pan_temp_c=pan_temperature_c,
            elapsed_sec=elapsed,
            heating_rate=heating_rate,
        )

        # b. Apply cumulative evaporation cooling
        lower_bound  = min(initial_food_temp_c, pan_temperature_c)
        current_temp = max(
            lower_bound,
            heated_temp - cumulative_cooling_c,
        )

        # c. Butter melting
        final_butter_melt = butter_melting.butter_melt_fraction(
            food_temp_c=current_temp,
            melt_start_c=melt_params["start_temperature_c"]["value"],
            melt_complete_c=melt_params["complete_temperature_c"]["value"],
        )

        # d. Protein denaturation (irreversible)
        current_denaturation = protein_denaturation.denaturation_fraction(
            food_temp_c=current_temp,
            start_temp_c=denat_params["start_temperature_c"]["value"],
            complete_temp_c=denat_params["complete_temperature_c"]["value"],
        )
        final_denaturation = max(final_denaturation, current_denaturation)

        # e. Water evaporation
        step_water_loss = water_evaporation.water_loss_per_step(
            food_temp_c=current_temp,
            time_step_sec=time_step_sec,
            evaporation_rate=evap_rate,
            current_water_mass_g=current_water_mass_g,
        )

        current_water_mass_g -= step_water_loss
        total_water_loss_g   += step_water_loss
        current_total_mass_g -= step_water_loss

        # f. Evaporation cooling feedback
        cooling_this_step = water_evaporation.evaporation_cooling_per_step(
            water_loss_g=step_water_loss,
            mixture_mass_g=current_total_mass_g,
        )
        cumulative_cooling_c += cooling_this_step

    # --- 7. Domain checks using final temperature ---
    domain_warnings += butter_melting.check_domain(current_temp)
    domain_warnings += protein_denaturation.check_domain(current_temp)
    domain_warnings += water_evaporation.check_domain(current_temp)

    # --- 8. Phase warnings ---
    phase_warnings = _check_phase_warnings(
        current_temp=current_temp,
        current_water_mass_g=current_water_mass_g,
        initial_water_mass_g=initial_water_mass_g,
    )

    estimated_water_loss_g = total_water_loss_g
    estimated_final_mass_g = current_total_mass_g

    # --- 9. Check physical invariants ---
    _check_invariants(
        estimated_final_mass_g=estimated_final_mass_g,
        initial_total_mass_g=initial_total_mass_g,
        estimated_water_loss_g=estimated_water_loss_g,
        initial_water_mass_g=initial_water_mass_g,
        current_temp=current_temp,
        initial_food_temp_c=initial_food_temp_c,
        pan_temperature_c=pan_temperature_c,
    )

    # --- 10. Build output dict ---
    domain_status = (
        "outside_declared_domain"
        if domain_warnings
        else "inside_declared_domain"
    )

    result = {
        "simulation_id": str(uuid.uuid4()),
        "timestamp":     datetime.now(timezone.utc).isoformat(),
        "recipe_id":     recipe_id,
        "model_version": "0.1.3",

        "inputs": {
            "pan_temperature_c":          pan_temperature_c,
            "duration_min":               duration_min,
            "initial_food_temperature_c": initial_food_temp_c,
            "time_step_sec":              time_step_sec,
        },

        "initial_state": {
            "total_mass_g": round(initial_total_mass_g, 3),
            "water_mass_g": round(initial_water_mass_g, 3),
            "initial_protein_denaturation_fraction": round(
                initial_denaturation, 4
            ),
        },

        "outputs": {
            "estimated_final_temperature_c": round(current_temp, 2),
            "cumulative_modeled_evaporative_temperature_reduction_c": round(
                cumulative_cooling_c, 3
            ),
            "butter_melt_fraction":          round(final_butter_melt, 4),
            "protein_denaturation_fraction": round(final_denaturation, 4),
            "coagulation_description": (
                protein_denaturation.describe_coagulation(
                    final_denaturation
                )
            ),
            "estimated_water_loss_g":  round(estimated_water_loss_g, 3),
            "remaining_water_mass_g":  round(current_water_mass_g, 3),
            "estimated_final_mass_g":  round(estimated_final_mass_g, 3),
        },

        "interpretation_status": (
            "model output, not sensory measurement"
        ),

        "domain_status":   domain_status,
        "domain_warnings": domain_warnings,
        "phase_warnings":  phase_warnings,
        "warnings":        warnings_list,

        "model_status":      "experimental",
        "validation_status": "not validated",

        "assumptions_active": [
            "A-HT-001: Pan temperature remains constant",
            "A-HT-002: Food mixture is thermally uniform",
            "A-HT-004: Stirring produces uniform temperature",
            "A-BM-001: Butter melting is linear between thresholds",
            "A-BM-002: Butter temperature equals mixture temperature",
            "A-PD-001: Egg white and yolk treated as uniform",
            "A-PD-002: Denaturation is linear between thresholds",
            "A-PD-003: Denaturation is irreversible",
            "A-PD-004: Time-at-temperature effects not modeled",
            "A-EV-001: Evaporation begins at 60°C threshold",
            "A-EV-002: Entire surface is exposed",
            "A-EV-003: Airflow is ignored",
            "A-EV-004: No crust formation modeled",
            "A-EV-005: No boiling transition modeled",
            "A-EV-006: Latent heat of water is constant at 2260 J/g",
            "A-EV-007: Mixture specific heat approximated as 3.7 J/(g*°C)",
            "A-EV-008: Evaporation cooling is instantaneous within each step",
            "A-SE-001: Denaturation fraction is primary driver of texture",
            "A-SE-002: Water content drives perceived moisture",
            "A-SE-003: Butter melt fraction drives perceived richness",
            "A-SE-004: Sensory relationships are linear within declared ranges",
            "A-SE-005: No cultural or individual perception variation modeled",
        ],
    }

    # --- 11. Generate sensory report ---
    result["sensory_report"] = sensory.generate_sensory_report(result)

    return result
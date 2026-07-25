"""
engine/simulate.py
FoodLab v0.1.7

Orchestrates the complete simulation pipeline.

Pipeline order:
  1.  Validate simulation inputs
  2.  Load and validate model parameters
  3.  Build initial mixture state
  4.  Initialise SimulationState
  5.  Run time-step loop:
       a. Estimate mixture temperature from heating model
       b. Apply cumulative evaporation cooling
       c. Calculate butter melting
       d. Calculate protein denaturation (irreversibility enforced)
       e. Calculate water evaporation
       f. Calculate evaporation cooling feedback
       g. Calculate effective surface temperature
       h. Update browning index (sigmoid onset, irreversible)
       i. Update cumulative high-temperature exposure
       j. Calculate burn index (sustained exposure)
       k. Calculate stickiness index
       l. Update elapsed time on state
       m. Record TimeStep snapshot into history
  6.  Domain checks using final state
  7.  Phase warnings
  8.  Physical invariants
  9.  Build SimulationResult
  10. Generate sensory report
  11. Detect milestone events
  12. Return result.to_dict()

Changes from v0.1.6:
  - SimulationState used to hold all evolving variables
  - TimeStep snapshots recorded every step into history list
  - SimulationResult constructed and returned
  - History enables post-simulation graphing and analysis
  - model_version bumped to 0.1.7
  - _check_invariants reads from SimulationState
  - Domain checks use state fields
  - Event detection added via engine.events.detect_events
  - events field populated on SimulationResult
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.events import detect_events                                # noqa: E402
from engine.state import SimulationResult, SimulationState, TimeStep   # noqa: E402
from models import (                                                   # noqa: E402
    browning,
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
            f"time_step_sec must be greater than zero. Got: {time_step_sec}"
        )
    if duration_min < 0:
        raise ValueError(
            f"duration_min must be non-negative. Got: {duration_min}"
        )
    if pan_temperature_c <= 0:
        raise ValueError(
            f"pan_temperature_c must be greater than zero. Got: {pan_temperature_c}"
        )
    if initial_food_temp_c < -273.15:
        raise ValueError(
            f"initial_food_temp_c is below absolute zero. Got: {initial_food_temp_c}"
        )


# ---------------------------------------------------------------------------
# Physical invariants — reads from SimulationState
# ---------------------------------------------------------------------------

def _check_invariants(
    state: SimulationState,
    initial_total_mass_g: float,
    initial_food_temp_c: float,
    pan_temperature_c: float,
) -> None:
    if state.total_mass_g < 0.0:
        raise RuntimeError(
            f"Invariant violation: total_mass_g became negative "
            f"({state.total_mass_g:.4f})."
        )
    if state.total_mass_g > initial_total_mass_g + 1e-6:
        raise RuntimeError(
            f"Invariant violation: total_mass_g ({state.total_mass_g:.4f}) "
            f"exceeds initial ({initial_total_mass_g:.4f})."
        )
    if state.total_water_loss_g > state.initial_water_mass_g + 1e-6:
        raise RuntimeError(
            f"Invariant violation: water loss ({state.total_water_loss_g:.4f}) "
            f"exceeds initial water ({state.initial_water_mass_g:.4f})."
        )
    upper_bound = max(initial_food_temp_c, pan_temperature_c)
    if state.food_temp_c > upper_bound + 1e-6:
        raise RuntimeError(
            f"Invariant violation: food_temp_c ({state.food_temp_c:.4f}) "
            f"exceeded boundary ({upper_bound:.4f})."
        )
    for name, value in [
        ("browning_index",                state.browning_index),
        ("burn_index",                    state.burn_index),
        ("stickiness_index",              state.stickiness_index),
        ("butter_melt_fraction",          state.butter_melt_fraction),
        ("protein_denaturation_fraction", state.protein_denaturation_fraction),
    ]:
        if not (-1e-6 <= value <= 1.0 + 1e-6):
            raise RuntimeError(
                f"Invariant violation: {name} ({value:.4f}) outside [0, 1]."
            )


# ---------------------------------------------------------------------------
# Phase warnings
# ---------------------------------------------------------------------------

def _check_phase_warnings(state: SimulationState) -> list[dict]:
    phase_warnings = []

    if state.food_temp_c > 100.0 and state.water_fraction > 0.1:
        phase_warnings.append({
            "code":                     "W-PHASE-001",
            "severity":                 "high",
            "model":                    "water_evaporation_v0.1",
            "mixture_temperature_c":    round(state.food_temp_c, 2),
            "water_fraction_remaining": round(state.water_fraction, 3),
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

def build_initial_state(recipe: dict, ingredients: dict) -> dict:
    """
    Calculates initial mixture mass and composition
    from recipe quantities and ingredient fractions.
    """
    total_mass_g    = 0.0
    total_water_g   = 0.0
    total_protein_g = 0.0
    total_fat_g     = 0.0

    for ing_id, ing_recipe in recipe["ingredients"].items():
        mass = ing_recipe["amount_g"]
        total_mass_g += mass

        comp = ingredients[ing_id].get("composition", {})

        total_water_g   += mass * comp.get("water_mass_fraction",   {}).get("value", 0.0)
        total_protein_g += mass * comp.get("protein_mass_fraction", {}).get("value", 0.0)
        total_fat_g     += mass * comp.get("fat_mass_fraction",     {}).get("value", 0.0)

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
    Runs the FoodLab v0.1.7 simulation pipeline.

    Returns a JSON-serialisable dict produced by SimulationResult.to_dict().
    The result includes a full timestep history suitable for graphing,
    post-simulation analysis, and milestone event detection.
    """

    warnings_list   = []
    domain_warnings = []

    # --- 1. Validate inputs ---
    _validate_inputs(
        pan_temperature_c, duration_min,
        initial_food_temp_c, time_step_sec,
    )

    # --- 2. Load model parameters ---
    heating_params  = parameters["mixture_heating_v0.1"]
    melt_params     = parameters["butter_melting_v0.1"]
    denat_params    = parameters["whole_egg_denaturation_v0.1"]
    evap_params     = parameters["water_evaporation_v0.1"]
    browning_params = parameters["browning_v0.1"]

    heating_rate   = heating_params["heating_rate_per_second"]["value"]
    evap_rate      = evap_params["evaporation_rate_g_per_sec_per_celsius"]["value"]
    br_pan_weight  = browning_params["pan_surface_weight"]["value"]
    br_base_rate   = browning_params["base_rate_per_second"]["value"]
    br_q10         = browning_params["q10_factor"]["value"]
    br_onset_c     = browning_params["onset_center_c"]["value"]
    br_steepness   = browning_params["onset_steepness"]["value"]
    br_mse         = browning_params["moisture_suppression_exponent"]["value"]
    burn_mult      = browning_params["burn_rate_multiplier"]["value"]
    st_prot_w      = browning_params["stickiness_protein_weight"]["value"]
    st_temp_w      = browning_params["stickiness_temp_weight"]["value"]
    st_butter_exp  = browning_params["butter_protection_exponent"]["value"]

    # Placeholder warnings
    placeholder_checks = [
        (
            heating_params["heating_rate_per_second"],
            "W-001", "high", "mixture_heating_v0.1",
            "Heating-rate parameter is an unfitted placeholder.",
            "Temperature and all dependent outputs are not validated.",
        ),
        (
            evap_params["evaporation_rate_g_per_sec_per_celsius"],
            "W-003", "high", "water_evaporation_v0.1",
            "Evaporation-rate parameter is an unfitted placeholder.",
            "Water loss estimate is not validated.",
        ),
        (
            browning_params["base_rate_per_second"],
            "W-004", "medium", "browning_v0.1",
            "Browning rate parameters are unfitted placeholders.",
            "Browning, burn, and stickiness values are not validated.",
        ),
    ]
    for param, code, severity, model, message, consequence in placeholder_checks:
        if param.get("status") == "unfitted_placeholder":
            warnings_list.append({
                "code":        code,
                "severity":    severity,
                "model":       model,
                "message":     message,
                "consequence": consequence,
            })

    # --- 3. Build initial composition ---
    initial_composition  = build_initial_state(recipe, ingredients)
    initial_total_mass_g = initial_composition["total_mass_g"]
    initial_water_mass_g = initial_composition["water_mass_g"]

    # --- 4. Domain check for heating model ---
    domain_warnings += mixture_heating.check_domain(
        initial_temp_c=initial_food_temp_c,
        pan_temp_c=pan_temperature_c,
        elapsed_sec=duration_min * 60.0,
    )

    # --- 5. Calculate t=0 fractions ---
    initial_denaturation = protein_denaturation.denaturation_fraction(
        food_temp_c=initial_food_temp_c,
        start_temp_c=denat_params["start_temperature_c"]["value"],
        complete_temp_c=denat_params["complete_temperature_c"]["value"],
    )
    initial_butter_melt = butter_melting.butter_melt_fraction(
        food_temp_c=initial_food_temp_c,
        melt_start_c=melt_params["start_temperature_c"]["value"],
        melt_complete_c=melt_params["complete_temperature_c"]["value"],
    )

    # --- 6. Initialise SimulationState ---
    state = SimulationState(
        food_temp_c=float(initial_food_temp_c),
        total_mass_g=initial_total_mass_g,
        water_mass_g=initial_water_mass_g,
        initial_water_mass_g=initial_water_mass_g,
        butter_melt_fraction=initial_butter_melt,
        protein_denaturation_fraction=initial_denaturation,
    )

    history: list[TimeStep] = []

    # --- 7. Time-step simulation loop ---
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
        lower_bound       = min(initial_food_temp_c, pan_temperature_c)
        state.food_temp_c = max(
            lower_bound,
            heated_temp - state.cumulative_evap_cooling_c,
        )

        # c. Butter melting
        state.butter_melt_fraction = butter_melting.butter_melt_fraction(
            food_temp_c=state.food_temp_c,
            melt_start_c=melt_params["start_temperature_c"]["value"],
            melt_complete_c=melt_params["complete_temperature_c"]["value"],
        )

        # d. Protein denaturation (irreversible)
        current_denaturation = protein_denaturation.denaturation_fraction(
            food_temp_c=state.food_temp_c,
            start_temp_c=denat_params["start_temperature_c"]["value"],
            complete_temp_c=denat_params["complete_temperature_c"]["value"],
        )
        state.protein_denaturation_fraction = max(
            state.protein_denaturation_fraction,
            current_denaturation,
        )

        # e. Water evaporation
        step_water_loss = water_evaporation.water_loss_per_step(
            food_temp_c=state.food_temp_c,
            time_step_sec=time_step_sec,
            evaporation_rate=evap_rate,
            current_water_mass_g=state.water_mass_g,
        )
        state.water_mass_g       -= step_water_loss
        state.total_mass_g       -= step_water_loss
        state.total_water_loss_g += step_water_loss

        # f. Evaporation cooling feedback
        cooling_this_step               = water_evaporation.evaporation_cooling_per_step(
            water_loss_g=step_water_loss,
            mixture_mass_g=state.total_mass_g,
        )
        state.cumulative_evap_cooling_c += cooling_this_step

        # g. Effective surface temperature
        state.effective_surface_temp_c = browning.effective_surface_temp(
            food_temp_c=state.food_temp_c,
            pan_temp_c=pan_temperature_c,
            pan_weight=br_pan_weight,
        )

        # h. Browning index (irreversible)
        state.browning_index = browning.browning_step(
            current_browning=state.browning_index,
            surface_temp_c=state.effective_surface_temp_c,
            water_fraction=state.water_fraction,
            time_step_sec=time_step_sec,
            base_rate=br_base_rate,
            q10_factor=br_q10,
            onset_center_c=br_onset_c,
            onset_steepness=br_steepness,
            moisture_suppression_exponent=br_mse,
        )

        # i. Cumulative high-temperature exposure
        state.high_temp_exposure_sec = browning.update_high_temp_exposure(
            current_exposure_sec=state.high_temp_exposure_sec,
            surface_temp_c=state.effective_surface_temp_c,
            time_step_sec=time_step_sec,
        )

        # j. Burn index (sustained exposure)
        state.burn_index = browning.burn_index(
            browning_index=state.browning_index,
            surface_temp_c=state.effective_surface_temp_c,
            water_fraction=state.water_fraction,
            cumulative_high_temp_sec=state.high_temp_exposure_sec,
            burn_rate_multiplier=burn_mult,
        )

        # k. Stickiness
        state.stickiness_index = browning.stickiness_index(
            protein_denaturation_fraction=state.protein_denaturation_fraction,
            butter_melt_fraction=state.butter_melt_fraction,
            surface_temp_c=state.effective_surface_temp_c,
            stickiness_protein_weight=st_prot_w,
            stickiness_temp_weight=st_temp_w,
            butter_protection_exponent=st_butter_exp,
        )

        # l. Update elapsed time
        state.elapsed_sec = elapsed

        # m. Record snapshot
        history.append(state.snapshot())

    # --- 8. Domain checks using final state ---
    domain_warnings += butter_melting.check_domain(state.food_temp_c)
    domain_warnings += protein_denaturation.check_domain(state.food_temp_c)
    domain_warnings += water_evaporation.check_domain(state.food_temp_c)
    domain_warnings += browning.check_domain(
        state.food_temp_c,
        pan_temperature_c,
        state.water_fraction,
    )

    # --- 9. Phase warnings ---
    phase_warnings = _check_phase_warnings(state)

    # --- 10. Physical invariants ---
    _check_invariants(
        state=state,
        initial_total_mass_g=initial_total_mass_g,
        initial_food_temp_c=initial_food_temp_c,
        pan_temperature_c=pan_temperature_c,
    )

    # --- 11. Build SimulationResult ---
    domain_status = (
        "outside_declared_domain" if domain_warnings
        else "inside_declared_domain"
    )

    outputs = {
        "estimated_final_temperature_c":    round(state.food_temp_c, 2),
        "effective_surface_temperature_c":  round(state.effective_surface_temp_c, 2),
        "cumulative_modeled_evaporative_temperature_reduction_c": round(
            state.cumulative_evap_cooling_c, 3
        ),
        "butter_melt_fraction":             round(state.butter_melt_fraction, 4),
        "protein_denaturation_fraction":    round(state.protein_denaturation_fraction, 4),
        "coagulation_description":          protein_denaturation.describe_coagulation(
            state.protein_denaturation_fraction
        ),
        "estimated_water_loss_g":           round(state.total_water_loss_g, 3),
        "remaining_water_mass_g":           round(state.water_mass_g, 3),
        "estimated_final_mass_g":           round(state.total_mass_g, 3),

        "browning_index":                   round(state.browning_index, 4),
        "browning_description":             browning.describe_browning(state.browning_index),
        "browning_bar":                     browning.progress_bar(state.browning_index),

        "burn_index":                       round(state.burn_index, 4),
        "burn_risk":                        browning.describe_burn_risk(state.burn_index),
        "burn_bar":                         browning.progress_bar(state.burn_index),

        "stickiness_index":                 round(state.stickiness_index, 4),
        "stickiness_description":           browning.describe_stickiness(state.stickiness_index),
        "stickiness_bar":                   browning.progress_bar(state.stickiness_index),

        "cumulative_high_temp_exposure_sec": round(state.high_temp_exposure_sec, 1),
    }

    assumptions = [
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
        "A-BR-001: Surface temp is weighted blend of food and pan temps",
        "A-BR-002: Browning onset uses sigmoid ramp not hard threshold",
        "A-BR-003: Browning depends on surface temp and water fraction only",
        "A-BR-004: Browning is irreversible",
        "A-BR-005: Burning accumulates from sustained high-temp exposure",
        "A-BR-006: Water activity approximated from water mass fraction",
        "A-BR-007: Stickiness depends on denaturation, butter, surface temp",
        "A-BR-008: Stirring not modeled — stickiness may be overestimated",
        "A-SE-001: Denaturation fraction is primary driver of texture",
        "A-SE-002: Water content drives perceived moisture",
        "A-SE-003: Butter melt fraction drives perceived richness",
        "A-SE-004: Sensory relationships are linear within declared ranges",
        "A-SE-005: No cultural or individual perception variation modeled",
    ]

    result = SimulationResult(
        recipe_id=recipe_id,
        model_version="0.1.7",
        inputs={
            "pan_temperature_c":          pan_temperature_c,
            "duration_min":               duration_min,
            "initial_food_temperature_c": initial_food_temp_c,
            "time_step_sec":              time_step_sec,
        },
        initial_state={
            "total_mass_g":  round(initial_total_mass_g, 3),
            "water_mass_g":  round(initial_water_mass_g, 3),
            "initial_protein_denaturation_fraction": round(initial_denaturation, 4),
        },
        outputs=outputs,
        warnings=warnings_list,
        domain_warnings=domain_warnings,
        phase_warnings=phase_warnings,
        assumptions=assumptions,
        history=history,
        metadata={
            "model_status":          "experimental",
            "validation_status":     "not validated",
            "domain_status":         domain_status,
            "interpretation_status": "model output, not sensory measurement",
        },
    )

    # --- 12. Sensory report ---
    result.sensory_report = sensory.generate_sensory_report(result.to_dict())

    # --- 13. Detect milestone events ---
    events        = detect_events(history)
    result.events = [e.to_dict() for e in events]

    return result.to_dict()
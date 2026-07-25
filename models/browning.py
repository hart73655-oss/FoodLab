"""
models/browning.py
FoodLab v0.1.6

Maillard browning, burn index, and stickiness models
for egg cooking on a pan surface.

The Maillard reaction is a chemical reaction between amino
acids and reducing sugars that produces brown color and
roasted flavor. It requires both heat and low moisture
to proceed significantly at food surfaces.

Browning in scrambled eggs occurs primarily at the surface
contacting the pan, not throughout the mixture. The bulk
food temperature significantly underestimates the surface
temperature that drives browning.

This model introduces effective_surface_temp as a simplified
weighted blend between food temperature and pan temperature.

Assumptions:
  A-BR-001: Effective surface temperature is a weighted blend
             of food and pan temperatures. Weights are model
             parameters, not derived from heat-transfer theory.
  A-BR-002: Browning rate uses a smooth sigmoid onset rather
             than a hard threshold. Onset curve shape is a
             model parameter, not fitted to data.
  A-BR-003: Browning depends on effective surface temperature
             and water fraction only, not on specific reactant
             concentrations.
  A-BR-004: Browning is irreversible.
  A-BR-005: Burning accumulates from cumulative time spent
             above a high-temperature threshold, not from
             instantaneous state alone.
  A-BR-006: Water activity is approximated from water mass
             fraction relative to initial water mass.
  A-BR-007: Stickiness depends on protein denaturation,
             butter melt fraction, and surface temperature.
  A-BR-008: Stirring is not modeled — stickiness may be
             overestimated for stirred recipes.

Ignores:
  Actual spatial temperature gradients within the egg
  Specific amino acid and sugar concentrations
  pH effects on browning rate
  Caramelization (higher temperatures, pure sugars)
  Acrylamide formation
  Colour measurement (CIE Lab or similar)
  Pan coating effects on stickiness beyond butter fraction

Valid domain:
  food_temp_c:    20 to 200°C
  pan_temp_c:     80 to 250°C
  water_fraction:  0.0 to 1.0

All rate constants are simplified model parameters.
None have been fitted to experimental data.
Status: unfitted_placeholder
"""

import math


DOMAIN = {
    "food_temp_c":    (20.0,  200.0),
    "pan_temp_c":     (80.0,  250.0),
    "water_fraction": (0.0,   1.0),
}

HIGH_TEMP_BURN_THRESHOLD_C = 170.0
BURNED_BROWNING_INDEX      = 0.90


# ---------------------------------------------------------------------------
# Domain check
# ---------------------------------------------------------------------------

def check_domain(
    food_temp_c: float,
    pan_temp_c: float,
    water_fraction: float,
) -> list[dict]:
    """
    Returns domain warning dicts.
    Does NOT clamp values.
    """
    warnings = []

    checks = [
        ("food_temp_c",    food_temp_c,    DOMAIN["food_temp_c"]),
        ("pan_temp_c",     pan_temp_c,     DOMAIN["pan_temp_c"]),
        ("water_fraction", water_fraction, DOMAIN["water_fraction"]),
    ]

    for name, value, (low, high) in checks:
        if not (low <= value <= high):
            warnings.append({
                "code":        "W-DOMAIN-BR",
                "severity":    "medium",
                "model":       "browning_v0.1",
                "parameter":   name,
                "requested":   value,
                "valid_range": [low, high],
                "message": (
                    f"{name} value {value} is outside "
                    f"declared domain [{low}, {high}]."
                ),
                "consequence": (
                    "Browning and burn index are extrapolations."
                ),
            })

    return warnings


# ---------------------------------------------------------------------------
# Effective surface temperature
# ---------------------------------------------------------------------------

def effective_surface_temp(
    food_temp_c: float,
    pan_temp_c: float,
    pan_weight: float,
) -> float:
    """
    Returns estimated effective surface temperature in Celsius.

    Uses a weighted blend as a simplified proxy for the
    actual surface temperature at the pan-food interface.

    Parameters
    ----------
    food_temp_c : float
        Bulk food mixture temperature in Celsius.
    pan_temp_c : float
        Pan surface temperature in Celsius.
    pan_weight : float
        Weight given to pan temperature (0.0 to 1.0).
        ~0.30 means surface ≈ 70% food + 30% pan.

    Returns
    -------
    float
        Effective surface temperature in Celsius.
    """
    pan_weight = max(0.0, min(1.0, pan_weight))
    return food_temp_c * (1.0 - pan_weight) + pan_temp_c * pan_weight


# ---------------------------------------------------------------------------
# Smooth browning onset (sigmoid)
# ---------------------------------------------------------------------------

def browning_onset_factor(
    surface_temp_c: float,
    onset_center_c: float,
    onset_steepness: float,
) -> float:
    """
    Returns a smooth onset factor between 0.0 and 1.0.

    Uses a sigmoid (logistic) function so browning begins
    gradually rather than switching on at a fixed temperature.

    Parameters
    ----------
    surface_temp_c : float
        Effective surface temperature in Celsius.
    onset_center_c : float
        Temperature at which onset factor equals 0.50.
    onset_steepness : float
        Controls how sharply onset transitions.

    Returns
    -------
    float
        Onset factor between 0.0 and 1.0.
    """
    exponent = -onset_steepness * (surface_temp_c - onset_center_c)
    exponent = max(-500.0, min(500.0, exponent))
    return 1.0 / (1.0 + math.exp(exponent))


# ---------------------------------------------------------------------------
# Browning rate
# ---------------------------------------------------------------------------

def browning_rate_per_second(
    surface_temp_c: float,
    water_fraction: float,
    base_rate: float,
    q10_factor: float,
    onset_center_c: float,
    onset_steepness: float,
    moisture_suppression_exponent: float,
) -> float:
    """
    Returns instantaneous browning rate (index units per second).

    Rate = base_rate
           × onset_factor
           × temperature_factor
           × moisture_suppression

    Returns
    -------
    float
        Browning rate >= 0.
    """
    if water_fraction < 0.0:
        water_fraction = 0.0

    onset       = browning_onset_factor(
        surface_temp_c, onset_center_c, onset_steepness
    )
    temp_excess  = max(0.0, surface_temp_c - onset_center_c)
    temp_factor  = q10_factor ** (temp_excess / 10.0)
    moisture_sup = (1.0 - water_fraction) ** moisture_suppression_exponent

    return max(0.0, base_rate * onset * temp_factor * moisture_sup)


# ---------------------------------------------------------------------------
# Browning step
# ---------------------------------------------------------------------------

def browning_step(
    current_browning: float,
    surface_temp_c: float,
    water_fraction: float,
    time_step_sec: float,
    base_rate: float,
    q10_factor: float,
    onset_center_c: float,
    onset_steepness: float,
    moisture_suppression_exponent: float,
) -> float:
    """
    Returns new browning index after one time step.

    Browning is irreversible. Index only increases.
    Clamped to [0.0, 1.0].
    """
    rate      = browning_rate_per_second(
        surface_temp_c,
        water_fraction,
        base_rate,
        q10_factor,
        onset_center_c,
        onset_steepness,
        moisture_suppression_exponent,
    )
    new_index = current_browning + rate * time_step_sec
    return max(0.0, min(1.0, new_index))


# ---------------------------------------------------------------------------
# Cumulative high-temperature exposure
# ---------------------------------------------------------------------------

def update_high_temp_exposure(
    current_exposure_sec: float,
    surface_temp_c: float,
    time_step_sec: float,
    high_temp_threshold_c: float = HIGH_TEMP_BURN_THRESHOLD_C,
) -> float:
    """
    Accumulates seconds spent above the high-temperature threshold.

    Burning requires sustained exposure, not just a momentary spike.
    """
    if surface_temp_c >= high_temp_threshold_c:
        return current_exposure_sec + time_step_sec
    return current_exposure_sec


# ---------------------------------------------------------------------------
# Burn index
# ---------------------------------------------------------------------------

def burn_index(
    browning_index: float,
    surface_temp_c: float,
    water_fraction: float,
    cumulative_high_temp_sec: float,
    burn_rate_multiplier: float,
    high_temp_threshold_c: float = HIGH_TEMP_BURN_THRESHOLD_C,
) -> float:
    """
    Returns a burn index (0.0 to 1.0).

    Burning is separate from browning.
    Depends on elevated browning AND sustained high-temperature exposure.

    Returns
    -------
    float
        Burn index between 0.0 and 1.0.
    """
    if browning_index < 0.50:
        return 0.0
    if cumulative_high_temp_sec <= 0.0:
        return 0.0

    browning_excess = browning_index - 0.50
    exposure_factor = 1.0 - math.exp(-cumulative_high_temp_sec / 120.0)
    dryness_factor  = max(0.0, 1.0 - water_fraction)
    temp_factor     = max(
        0.0,
        (surface_temp_c - high_temp_threshold_c) / high_temp_threshold_c,
    )

    raw = (
        browning_excess
        * exposure_factor
        * (1.0 + dryness_factor)
        * (1.0 + temp_factor)
        * burn_rate_multiplier
    )

    return max(0.0, min(1.0, raw))


# ---------------------------------------------------------------------------
# Stickiness
# ---------------------------------------------------------------------------

def stickiness_index(
    protein_denaturation_fraction: float,
    butter_melt_fraction: float,
    surface_temp_c: float,
    stickiness_protein_weight: float,
    stickiness_temp_weight: float,
    butter_protection_exponent: float,
) -> float:
    """
    Returns a stickiness index (0.0 to 1.0).

    Eggs stick when denatured proteins bond with the pan surface.
    Butter creates a barrier that reduces contact.
    Higher surface temperatures accelerate bonding.

    Returns
    -------
    float
        Stickiness index between 0.0 and 1.0.
    """
    protein_factor = protein_denaturation_fraction * stickiness_protein_weight
    temp_factor    = max(
        0.0,
        (surface_temp_c - 62.0) / 100.0,
    ) * stickiness_temp_weight

    raw_stickiness   = min(1.0, protein_factor + temp_factor)
    butter_protection = butter_melt_fraction ** butter_protection_exponent
    final_stickiness  = raw_stickiness * (1.0 - butter_protection * 0.8)

    return max(0.0, min(1.0, final_stickiness))


# ---------------------------------------------------------------------------
# Descriptors
# ---------------------------------------------------------------------------

def describe_browning(browning_index: float) -> str:
    """
    Returns plain-language browning descriptor.
    Thresholds are model choices, not validated standards.
    """
    if browning_index < 0.05:
        return "none"
    elif browning_index < 0.15:
        return "very light"
    elif browning_index < 0.35:
        return "light"
    elif browning_index < 0.55:
        return "moderate"
    elif browning_index < 0.75:
        return "dark"
    elif browning_index < BURNED_BROWNING_INDEX:
        return "very dark"
    else:
        return "burned"


def describe_burn_risk(burn_index_value: float) -> str:
    """
    Returns burn risk label.
    Thresholds are model choices, not validated standards.
    """
    if burn_index_value < 0.05:
        return "none"
    elif burn_index_value < 0.25:
        return "low"
    elif burn_index_value < 0.50:
        return "moderate"
    elif burn_index_value < 0.75:
        return "high"
    else:
        return "burned"


def describe_stickiness(stickiness_index_value: float) -> str:
    """
    Returns stickiness label.
    Thresholds are model choices, not validated standards.
    """
    if stickiness_index_value < 0.10:
        return "none"
    elif stickiness_index_value < 0.30:
        return "low"
    elif stickiness_index_value < 0.55:
        return "moderate"
    elif stickiness_index_value < 0.80:
        return "high"
    else:
        return "extreme"


# ---------------------------------------------------------------------------
# Progress bar renderer
# ---------------------------------------------------------------------------

def progress_bar(
    value: float,
    width: int = 10,
    fill: str = "█",
    empty: str = "░",
) -> str:
    """
    Returns a Unicode progress bar string.

    Example:
      progress_bar(0.52) → "█████░░░░░  52%"
    """
    value      = max(0.0, min(1.0, value))
    filled     = round(value * width)
    bar        = fill * filled + empty * (width - filled)
    percentage = round(value * 100)
    return f"{bar}  {percentage}%"
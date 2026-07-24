"""
Model: Simplified Lumped Heating Approximation
Version: 0.1.0
Status: Experimental — not validated

Assumptions:
  A-HT-001: Pan temperature is constant
  A-HT-002: Food mixture is thermally uniform
  A-HT-003: Evaporation cooling is ignored
  A-HT-004: Stirring produces uniform temperature

Ignores:
  Convection within mixture
  Radiation
  Steam formation
  Contact area changes during stirring
  Egg white vs yolk thermal differences

Valid domain:
  initial_temp_c:  15.0 to  25.0
  pan_temp_c:     100.0 to 170.0
  elapsed_sec:      0.0 to 600.0

heating_rate is a model parameter.
It is NOT an ingredient property.
Current value is an unfitted placeholder.
See: data/model_parameters.json
"""

import math


DOMAIN = {
    "initial_temp_c": (15.0, 25.0),
    "pan_temp_c":     (100.0, 170.0),
    "elapsed_sec":    (0.0, 600.0),
}


def check_domain(
    initial_temp_c: float,
    pan_temp_c: float,
    elapsed_sec: float,
) -> list[dict]:
    """
    Returns list of domain warning dicts.
    Empty list means all inputs are inside declared domain.
    Does NOT clamp values.
    """
    warnings = []

    checks = [
        ("initial_temp_c", initial_temp_c),
        ("pan_temp_c",     pan_temp_c),
        ("elapsed_sec",    elapsed_sec),
    ]

    for name, value in checks:
        low, high = DOMAIN[name]
        if not (low <= value <= high):
            warnings.append({
                "code": "W-DOMAIN-HT",
                "severity": "high",
                "model": "mixture_heating_v0.1",
                "parameter": name,
                "requested": value,
                "valid_range": [low, high],
                "message": (
                    f"{name} value {value} is outside "
                    f"declared domain [{low}, {high}]."
                ),
                "consequence": (
                    "Result is an extrapolation "
                    "and has not been validated."
                ),
            })

    return warnings


def estimate_food_temperature(
    initial_temp_c: float,
    pan_temp_c: float,
    elapsed_sec: float,
    heating_rate: float,
) -> float:
    """
    Returns estimated food temperature at elapsed_sec.

    Supports both heating and cooling correctly.
    Will not exceed the hotter of the two boundary temperatures.
    Will not fall below the cooler of the two boundary temperatures.

    Parameters
    ----------
    initial_temp_c : float
        Starting food temperature in Celsius.
    pan_temp_c : float
        Constant pan surface temperature in Celsius.
    elapsed_sec : float
        Time since cooking began, in seconds.
    heating_rate : float
        Model parameter in 1/second.
        Current value is an unfitted placeholder.

    Returns
    -------
    float
        Estimated food temperature in Celsius.

    Raises
    ------
    ValueError
        If elapsed_sec is negative.
    """

    if elapsed_sec < 0:
        raise ValueError(
            f"elapsed_sec must be non-negative. Got: {elapsed_sec}"
        )

    if elapsed_sec == 0:
        return float(initial_temp_c)

    fraction = 1.0 - math.exp(-heating_rate * elapsed_sec)
    temperature = initial_temp_c + (
        pan_temp_c - initial_temp_c
    ) * fraction

    # Correct clamp that supports both heating and cooling
    lower_bound = min(initial_temp_c, pan_temp_c)
    upper_bound = max(initial_temp_c, pan_temp_c)

    return max(lower_bound, min(temperature, upper_bound))
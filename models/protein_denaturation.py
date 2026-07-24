"""
Model: Simplified Whole Egg Protein Denaturation
Version: 0.1.0
Status: Experimental — not validated

Assumptions:
  A-PD-001: Egg white and yolk treated as one uniform material
  A-PD-002: Denaturation is linear between start and complete temperatures
  A-PD-003: Denaturation is irreversible
  A-PD-004: Time-at-temperature effects are not modeled

Ignores:
  Egg white vs yolk differences
  Hold time effects
  pH effects on denaturation temperature

Valid domain:
  food_temp_c: 20.0 to 90.0
"""


DOMAIN = {
    "food_temp_c": (20.0, 90.0),
}


def check_domain(food_temp_c: float) -> list[dict]:
    """
    Returns list of domain warning dicts.
    Empty list means input is inside declared domain.
    Does NOT clamp values.
    """
    warnings = []
    low, high = DOMAIN["food_temp_c"]

    if not (low <= food_temp_c <= high):
        warnings.append({
            "code": "W-DOMAIN-PD",
            "severity": "high",
            "model": "protein_denaturation_v0.1",
            "parameter": "food_temp_c",
            "requested": food_temp_c,
            "valid_range": [low, high],
            "message": (
                f"food_temp_c {food_temp_c} is outside "
                f"declared domain [{low}, {high}]."
            ),
            "consequence": (
                "Denaturation fraction is an extrapolation."
            ),
        })

    return warnings


def validate_thresholds(
    start_temp_c: float,
    complete_temp_c: float,
) -> None:
    """
    Raises ValueError if thresholds are inverted or equal.
    Prevents division by zero and reversed behaviour.
    """
    if complete_temp_c <= start_temp_c:
        raise ValueError(
            "complete_temp_c must be greater than start_temp_c. "
            f"Got start={start_temp_c}, complete={complete_temp_c}"
        )


def denaturation_fraction(
    food_temp_c: float,
    start_temp_c: float,
    complete_temp_c: float,
) -> float:
    """
    Returns fraction of protein denatured (0.0 to 1.0).

    Denaturation is declared irreversible in this model.
    The engine enforces irreversibility using max() across time steps.

    Parameters
    ----------
    food_temp_c : float
        Current food mixture temperature in Celsius.
    start_temp_c : float
        Temperature at which denaturation begins.
        Source: model_parameters.json
    complete_temp_c : float
        Temperature at which denaturation is complete.
        Source: model_parameters.json

    Returns
    -------
    float
        Denaturation fraction between 0.0 and 1.0 inclusive.
    """
    validate_thresholds(start_temp_c, complete_temp_c)

    if food_temp_c <= start_temp_c:
        return 0.0
    if food_temp_c >= complete_temp_c:
        return 1.0

    return (food_temp_c - start_temp_c) / (complete_temp_c - start_temp_c)


def describe_coagulation(fraction: float) -> str:
    """
    Converts denaturation fraction to a descriptive label.

    This is an interpretation rule, not a sensory measurement.
    Thresholds are model choices, not validated standards.
    See: docs/MODEL_CARDS/protein_denaturation.md

    Raises
    ------
    ValueError
        If fraction is outside [0.0, 1.0].
    """
    if not (0.0 <= fraction <= 1.0):
        raise ValueError(
            f"fraction must be between 0.0 and 1.0. Got: {fraction}"
        )

    if fraction < 0.4:
        return "low modeled coagulation"
    elif fraction < 0.75:
        return "moderate modeled coagulation"
    else:
        return "high modeled coagulation"
"""
Model: Simplified Butter Melting
Version: 0.1.0
Status: Experimental — not validated

Assumptions:
  A-BM-001: Melting is linear between start and complete temperatures
  A-BM-002: Butter temperature equals mixture temperature

Ignores:
  Heat of fusion
  Partial melting effects on heat transfer

Valid domain:
  food_temp_c: 20.0 to 60.0
"""


DOMAIN = {
    "food_temp_c": (20.0, 60.0),
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
            "code": "W-DOMAIN-BM",
            "severity": "medium",
            "model": "butter_melting_v0.1",
            "parameter": "food_temp_c",
            "requested": food_temp_c,
            "valid_range": [low, high],
            "message": (
                f"food_temp_c {food_temp_c} is outside "
                f"declared domain [{low}, {high}]."
            ),
            "consequence": (
                "Butter melt fraction is an extrapolation."
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


def butter_melt_fraction(
    food_temp_c: float,
    melt_start_c: float,
    melt_complete_c: float,
) -> float:
    """
    Returns fraction of butter melted (0.0 to 1.0).

    Parameters
    ----------
    food_temp_c : float
        Current food mixture temperature in Celsius.
    melt_start_c : float
        Temperature at which melting begins.
        Source: model_parameters.json
    melt_complete_c : float
        Temperature at which melting is complete.
        Source: model_parameters.json

    Returns
    -------
    float
        Melt fraction between 0.0 and 1.0 inclusive.
    """
    validate_thresholds(melt_start_c, melt_complete_c)

    if food_temp_c <= melt_start_c:
        return 0.0
    if food_temp_c >= melt_complete_c:
        return 1.0

    return (food_temp_c - melt_start_c) / (melt_complete_c - melt_start_c)
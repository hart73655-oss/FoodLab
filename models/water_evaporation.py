"""
Model: Simplified Surface Evaporation
Version: 0.1.1
Status: Experimental — not validated

Estimates water loss from food surface per time step.
Includes evaporation cooling feedback.

Changes from v0.1.0:
  - Evaporation now begins at 60°C threshold, not 0°C
  - Only temperature above 60°C drives evaporation rate
  - Added evaporation_cooling_per_step function
  - Model behavior now matches declared domain

Assumptions:
  A-EV-001: Evaporation rate scales linearly with temperature above 60°C
  A-EV-002: Entire surface is exposed
  A-EV-003: Airflow is ignored
  A-EV-004: No crust formation reducing evaporation area
  A-EV-005: No distinction between surface evaporation and boiling
  A-EV-006: Latent heat of water is constant at 2260 J/g
  A-EV-007: Mixture specific heat is approximated as 3.7 J/(g*°C)
  A-EV-008: Evaporation cooling is instantaneous within each time step

Ignores:
  Relative humidity of environment
  Airflow velocity
  Surface area changes during cooking
  Crust formation
  Boiling transition at 100°C
  Temperature dependence of latent heat
  Composition dependence of specific heat

Valid domain:
  food_temp_c:  60.0 to 100.0

evaporation_rate is a model parameter.
It is NOT an ingredient property.
Current value is an unfitted placeholder.
See: data/model_parameters.json
"""


DOMAIN = {
    "food_temp_c": (60.0, 100.0),
}

EVAPORATION_THRESHOLD_C = 60.0
LATENT_HEAT_WATER_J_PER_G = 2260.0


def check_domain(food_temp_c: float) -> list[dict]:
    """
    Returns domain warning dicts.
    Empty list means input is inside declared domain.
    Does NOT clamp values.
    """
    warnings = []
    low, high = DOMAIN["food_temp_c"]

    if not (low <= food_temp_c <= high):
        warnings.append({
            "code": "W-DOMAIN-EV",
            "severity": "medium",
            "model": "water_evaporation_v0.1",
            "parameter": "food_temp_c",
            "requested": food_temp_c,
            "valid_range": [low, high],
            "message": (
                f"food_temp_c {food_temp_c} is outside "
                f"declared domain [{low}, {high}]."
            ),
            "consequence": (
                "Water loss estimate is an extrapolation."
            ),
        })

    return warnings


def water_loss_per_step(
    food_temp_c: float,
    time_step_sec: float,
    evaporation_rate: float,
    current_water_mass_g: float,
) -> float:
    """
    Returns estimated water lost in one time step in grams.

    Evaporation begins at 60°C, matching the declared model domain.
    Only temperature above 60°C drives the evaporation rate.
    Below 60°C this function returns 0.0.

    Parameters
    ----------
    food_temp_c : float
        Current food temperature in Celsius.
    time_step_sec : float
        Duration of this time step in seconds.
    evaporation_rate : float
        Model parameter in g/(s * °C above threshold).
        Current value is an unfitted placeholder.
    current_water_mass_g : float
        Remaining water mass in grams before this step.

    Returns
    -------
    float
        Water lost this step in grams.
        Returns 0.0 below 60°C.
        Always between 0.0 and current_water_mass_g.
    """
    if food_temp_c < EVAPORATION_THRESHOLD_C:
        return 0.0

    if current_water_mass_g <= 0.0:
        return 0.0

    effective_temp = food_temp_c - EVAPORATION_THRESHOLD_C
    loss = evaporation_rate * effective_temp * time_step_sec

    return max(0.0, min(loss, current_water_mass_g))


def evaporation_cooling_per_step(
    water_loss_g: float,
    mixture_mass_g: float,
    specific_heat_j_per_g_c: float = 3.7,
) -> float:
    """
    Estimates temperature drop caused by evaporation in one time step.

    Uses energy balance:
      energy removed = water_loss_g * latent_heat
      temperature drop = energy_removed / (mixture_mass * specific_heat)

    Assumptions:
      A-EV-006: Latent heat of water is constant at 2260 J/g
      A-EV-007: Mixture specific heat approximated as 3.7 J/(g*°C)
      A-EV-008: Cooling is instantaneous within the time step

    Parameters
    ----------
    water_loss_g : float
        Water evaporated this time step in grams.
    mixture_mass_g : float
        Current total mixture mass in grams.
    specific_heat_j_per_g_c : float
        Approximate specific heat of the mixture in J/(g*°C).
        Default 3.7 is a simplified placeholder for a wet egg mixture.
        This value has not been validated.

    Returns
    -------
    float
        Temperature drop in Celsius for this time step.
        Always >= 0.0.
    """
    if mixture_mass_g <= 0.0:
        return 0.0

    if water_loss_g <= 0.0:
        return 0.0

    energy_removed_j = water_loss_g * LATENT_HEAT_WATER_J_PER_G
    temp_drop_c = energy_removed_j / (
        mixture_mass_g * specific_heat_j_per_g_c
    )

    return max(0.0, temp_drop_c)
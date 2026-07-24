"""
Model: Sensory Interpretation
Version: 0.1.0
Status: Experimental — not validated

Converts physical simulation outputs into estimated
sensory descriptors.

IMPORTANT LIMITATION:
  This module does not predict taste directly.
  It applies interpretation rules to physical outputs.
  All scores are model outputs, not sensory measurements.
  Human perception depends on genetics, culture, temperature,
  mood, memory, and many factors this model does not capture.

  If the upstream physics is unvalidated, all sensory
  outputs derived from it are also unvalidated.

Assumptions:
  A-SE-001: Denaturation fraction is the primary driver of texture
  A-SE-002: Water content drives perceived moisture and creaminess
  A-SE-003: Butter melt fraction drives perceived richness
  A-SE-004: Sensory relationships are linear within declared ranges
  A-SE-005: No cultural, genetic, or individual variation modeled

Ignores:
  Human perception variability
  Cultural preferences
  Serving temperature effects
  Seasoning interactions beyond salt distribution
  Maillard browning (not yet modeled in physics)
  Volatile aroma compounds
  Texture heterogeneity
"""


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------

def calculate_physics_confidence(simulation_result: dict) -> dict:
    """
    Evaluates how much trust to place in the physics output.

    Returns a confidence record that must be attached to
    every sensory report.
    """
    high_severity   = 0
    medium_severity = 0
    unvalidated     = simulation_result.get(
        "validation_status", ""
    ) != "validated"
    phase_issues    = len(simulation_result.get("phase_warnings", [])) > 0

    for w in simulation_result.get("warnings", []):
        if w.get("severity") == "high":
            high_severity += 1
        elif w.get("severity") == "medium":
            medium_severity += 1

    for w in simulation_result.get("domain_warnings", []):
        if w.get("severity") == "high":
            high_severity += 1
        elif w.get("severity") == "medium":
            medium_severity += 1

    if high_severity > 0 or phase_issues:
        level       = "very_low"
        description = (
            "Physics output contains high-severity warnings or "
            "phase violations. Sensory scores are speculative."
        )
    elif medium_severity > 0 or unvalidated:
        level       = "low"
        description = (
            "Physics output is unvalidated or contains medium "
            "warnings. Sensory scores are indicative only."
        )
    else:
        level       = "moderate"
        description = (
            "Physics output passed domain checks. "
            "Sensory scores are model estimates, not measurements."
        )

    return {
        "level":                    level,
        "description":              description,
        "high_severity_warnings":   high_severity,
        "medium_severity_warnings": medium_severity,
        "phase_warnings_present":   phase_issues,
        "physics_validated":        not unvalidated,
    }


# ---------------------------------------------------------------------------
# Individual sensory dimensions
# ---------------------------------------------------------------------------

def estimate_texture(denaturation_fraction: float) -> dict:
    """
    Estimates texture descriptor from protein denaturation fraction.

    Thresholds are model choices, not validated standards.
    """
    if denaturation_fraction < 0.3:
        descriptor = "liquid, unset"
        score      = 0.2
    elif denaturation_fraction < 0.6:
        descriptor = "soft, custardy"
        score      = 0.8
    elif denaturation_fraction < 0.85:
        descriptor = "set, tender"
        score      = 0.65
    else:
        descriptor = "firm, possibly rubbery"
        score      = 0.35

    return {
        "score":                round(score, 3),
        "descriptor":           descriptor,
        "basis":                "denaturation_fraction",
        "input_value":          round(denaturation_fraction, 4),
        "interpretation_status": "model rule, not sensory measurement",
    }


def estimate_moisture(
    remaining_water_mass_g: float,
    initial_water_mass_g: float,
) -> dict:
    """
    Estimates perceived moisture from remaining water fraction.
    """
    if initial_water_mass_g <= 0.0:
        water_fraction = 0.0
    else:
        water_fraction = remaining_water_mass_g / initial_water_mass_g

    if water_fraction > 0.9:
        descriptor = "very moist"
        score      = 0.9
    elif water_fraction > 0.75:
        descriptor = "moist"
        score      = 0.75
    elif water_fraction > 0.55:
        descriptor = "slightly dry"
        score      = 0.5
    else:
        descriptor = "dry"
        score      = 0.25

    return {
        "score":                   round(score, 3),
        "descriptor":              descriptor,
        "water_fraction_remaining": round(water_fraction, 4),
        "basis":                   "remaining_water_mass / initial_water_mass",
        "interpretation_status":   "model rule, not sensory measurement",
    }


def estimate_richness(butter_melt_fraction: float) -> dict:
    """
    Estimates perceived richness from butter melt fraction.
    """
    if butter_melt_fraction > 0.9:
        descriptor = "rich, buttery"
        score      = 0.9
    elif butter_melt_fraction > 0.5:
        descriptor = "noticeable butter"
        score      = 0.65
    elif butter_melt_fraction > 0.1:
        descriptor = "slight butter presence"
        score      = 0.4
    else:
        descriptor = "minimal butter presence"
        score      = 0.2

    return {
        "score":                round(score, 3),
        "descriptor":           descriptor,
        "basis":                "butter_melt_fraction",
        "input_value":          round(butter_melt_fraction, 4),
        "interpretation_status": "model rule, not sensory measurement",
    }


def generate_chef_note(
    texture:           dict,
    moisture:          dict,
    richness:          dict,
    physics_confidence: dict,
) -> str:
    """
    Generates a plain-language note based on sensory dimensions.
    Leads with a caveat when confidence is very_low.
    """
    if physics_confidence["level"] == "very_low":
        prefix = "Physics warnings present. Notes are speculative. | "
    elif physics_confidence["level"] == "low":
        prefix = "Indicative only. | "
    else:
        prefix = ""

    parts = []

    if texture["score"] >= 0.7:
        parts.append("well-set texture")
    elif texture["score"] >= 0.5:
        parts.append("tender texture")
    else:
        parts.append("firm or rubbery texture")

    if moisture["score"] >= 0.7:
        parts.append("good moisture retention")
    else:
        parts.append("reduced moisture")

    if richness["score"] >= 0.7:
        parts.append("rich buttery flavor")
    elif richness["score"] >= 0.4:
        parts.append("noticeable butter")
    else:
        parts.append("light butter presence")

    return prefix + ", ".join(parts) + "."


# ---------------------------------------------------------------------------
# Main sensory report function
# ---------------------------------------------------------------------------

def generate_sensory_report(simulation_result: dict) -> dict:
    """
    Generates a sensory report from a simulation result dict.

    Always includes:
      physics_confidence  — how much to trust the physics input
      dimensions          — texture, moisture, richness
      chef_note           — plain-language summary
      interpretation_status — reminds reader these are model outputs

    Must not be presented as a taste measurement.
    """
    outputs = simulation_result["outputs"]
    initial = simulation_result["initial_state"]

    physics_confidence = calculate_physics_confidence(simulation_result)

    texture = estimate_texture(
        denaturation_fraction=outputs["protein_denaturation_fraction"],
    )
    moisture = estimate_moisture(
        remaining_water_mass_g=outputs["remaining_water_mass_g"],
        initial_water_mass_g=initial["water_mass_g"],
    )
    richness = estimate_richness(
        butter_melt_fraction=outputs["butter_melt_fraction"],
    )
    chef_note = generate_chef_note(
        texture=texture,
        moisture=moisture,
        richness=richness,
        physics_confidence=physics_confidence,
    )

    return {
        "sensory_model_version": "0.1.0",
        "interpretation_status": (
            "model output derived from physics simulation. "
            "Not a sensory measurement. "
            "Not validated against human tasting panels."
        ),
        "physics_confidence": physics_confidence,
        "dimensions": {
            "texture":  texture,
            "moisture": moisture,
            "richness": richness,
        },
        "chef_note": chef_note,
        "not_yet_modeled": [
            "browning and Maillard flavor",
            "aroma compounds",
            "saltiness from salt distribution",
            "temperature at serving",
            "visual appearance and color",
            "individual perception variability",
        ],
    }
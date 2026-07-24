"""
Model: Sensory Interpretation
Version: 0.1.2
Status: Experimental — not validated

Converts physical simulation outputs into estimated
sensory descriptors.

Changes from v0.1.1:
  - physics_confidence now includes a numerical score (0.0 to 1.0)
    calculated from active warnings, phase violations, and
    validation status.
  - confidence score automatically increases as physics improves.
  - reason list documents exactly why confidence is reduced.
  - Texture, moisture, and richness now report sub-dimensions
    where physically supportable.
  - Appearance block added (color, surface description).
  - Chef assessment added based on combined sensory state.
  - All suppression logic from v0.1.1 retained.

IMPORTANT LIMITATION:
  This module does not predict taste directly.
  It applies interpretation rules to physical outputs.
  All scores are model outputs, not sensory measurements.
  Human perception depends on genetics, culture, temperature,
  mood, memory, and many factors this model does not capture.

  When a phase-state violation is detected (W-PHASE-001),
  texture and moisture are suppressed rather than presenting
  scores derived from a physically invalid state.

Assumptions:
  A-SE-001: Denaturation fraction is the primary driver of texture
  A-SE-002: Water content drives perceived moisture and creaminess
  A-SE-003: Butter melt fraction drives perceived richness
  A-SE-004: Sensory relationships are linear within declared ranges
  A-SE-005: No cultural, genetic, or individual variation modeled
  A-SE-006: Appearance is estimated from denaturation and water fraction
  A-SE-007: Chef assessment uses fixed threshold rules

Ignores:
  Human perception variability
  Cultural preferences
  Serving temperature effects
  Maillard browning (not yet modeled in physics)
  Volatile aroma compounds
  Texture heterogeneity
  Curd size and structure
  Visual color from browning
"""


PHASE_INVALID_DESCRIPTOR = (
    "unreliable — phase-state violation active (W-PHASE-001). "
    "Predicted temperature exceeds boiling region while substantial "
    "water remains. Sensory prediction from this state is not meaningful."
)


# ---------------------------------------------------------------------------
# Numerical confidence score
# ---------------------------------------------------------------------------

def calculate_physics_confidence(simulation_result: dict) -> dict:
    """
    Evaluates how much trust to place in the physics output.

    Returns a confidence record with:
      score   float 0.0 to 1.0
      label   very_low / low / moderate / high
      reason  list of strings explaining each deduction

    Score deductions:
      Phase violation active          -0.40
      Per high-severity warning       -0.15 (capped at -0.30)
      Per medium-severity warning     -0.05 (capped at -0.10)
      Physics not validated           -0.10

    Score starts at 1.0 and deductions are applied.
    Score is clamped to [0.0, 1.0].
    """
    score   = 1.0
    reasons = []

    high_count   = 0
    medium_count = 0

    for w in simulation_result.get("warnings", []):
        sev = w.get("severity", "")
        if sev == "high":
            high_count += 1
        elif sev == "medium":
            medium_count += 1

    for w in simulation_result.get("domain_warnings", []):
        sev = w.get("severity", "")
        if sev == "high":
            high_count += 1
        elif sev == "medium":
            medium_count += 1

    phase_issues = len(simulation_result.get("phase_warnings", [])) > 0
    unvalidated  = simulation_result.get(
        "validation_status", ""
    ) != "validated"

    if phase_issues:
        score -= 0.40
        reasons.append(
            "phase-state violation active — temperature above boiling "
            "while water remains (W-PHASE-001)"
        )

    high_deduction = min(high_count * 0.15, 0.30)
    if high_deduction > 0:
        score -= high_deduction
        reasons.append(
            f"{high_count} high-severity warning(s) active "
            f"(deduction {high_deduction:.2f})"
        )

    medium_deduction = min(medium_count * 0.05, 0.10)
    if medium_deduction > 0:
        score -= medium_deduction
        reasons.append(
            f"{medium_count} medium-severity warning(s) active "
            f"(deduction {medium_deduction:.2f})"
        )

    if unvalidated:
        score -= 0.10
        reasons.append("physics model not yet experimentally validated")

    score = max(0.0, min(1.0, score))

    if score >= 0.75:
        label       = "high"
        description = (
            "Physics output is validated and within declared domains. "
            "Sensory estimates are model-based and may be used indicatively."
        )
    elif score >= 0.50:
        label       = "moderate"
        description = (
            "Physics output passed domain checks with minor warnings. "
            "Sensory scores are model estimates, not measurements."
        )
    elif score >= 0.25:
        label       = "low"
        description = (
            "Physics output is unvalidated or contains warnings. "
            "Sensory scores are indicative only."
        )
    else:
        label       = "very_low"
        description = (
            "Physics output contains major warnings or phase violations. "
            "Sensory scores are suppressed or speculative."
        )

    return {
        "score":                    round(score, 3),
        "label":                    label,
        "description":              description,
        "reason":                   reasons,
        "high_severity_warnings":   high_count,
        "medium_severity_warnings": medium_count,
        "phase_warnings_present":   phase_issues,
        "physics_validated":        not unvalidated,
    }


# ---------------------------------------------------------------------------
# Phase-state check
# ---------------------------------------------------------------------------

def _phase_violation_active(simulation_result: dict) -> bool:
    return len(simulation_result.get("phase_warnings", [])) > 0


# ---------------------------------------------------------------------------
# Texture
# ---------------------------------------------------------------------------

def estimate_texture(denaturation_fraction: float) -> dict:
    """
    Estimates texture descriptors from protein denaturation fraction.

    Sub-dimensions:
      firmness    increases with denaturation
      creaminess  peaks at moderate denaturation, falls at full set
      fluffiness  peaks at moderate denaturation
    """
    if denaturation_fraction < 0.3:
        descriptor = "liquid, unset"
        firmness   = round(denaturation_fraction * 2.0, 3)
        creaminess = round(0.2, 3)
        fluffiness = round(0.3, 3)
    elif denaturation_fraction < 0.6:
        descriptor = "soft, custardy"
        firmness   = round(0.3 + denaturation_fraction * 0.5, 3)
        creaminess = round(0.8, 3)
        fluffiness = round(0.75, 3)
    elif denaturation_fraction < 0.85:
        descriptor = "set, tender"
        firmness   = round(0.6 + denaturation_fraction * 0.3, 3)
        creaminess = round(0.5, 3)
        fluffiness = round(0.55, 3)
    else:
        descriptor = "firm, possibly rubbery"
        firmness   = round(0.85 + denaturation_fraction * 0.15, 3)
        creaminess = round(0.15, 3)
        fluffiness = round(0.2, 3)

    return {
        "descriptor":            descriptor,
        "sub_dimensions": {
            "firmness":   {"score": min(firmness, 1.0),   "unit": "0–1"},
            "creaminess": {"score": min(creaminess, 1.0), "unit": "0–1"},
            "fluffiness": {"score": min(fluffiness, 1.0), "unit": "0–1"},
        },
        "basis":                 "protein_denaturation_fraction",
        "input_value":           round(denaturation_fraction, 4),
        "interpretation_status": "model rule, not sensory measurement",
    }


# ---------------------------------------------------------------------------
# Moisture
# ---------------------------------------------------------------------------

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
        "descriptor":               descriptor,
        "score":                    round(score, 3),
        "water_fraction_remaining": round(water_fraction, 4),
        "basis":                    "remaining_water_mass / initial_water_mass",
        "interpretation_status":    "model rule, not sensory measurement",
    }


# ---------------------------------------------------------------------------
# Richness
# ---------------------------------------------------------------------------

def estimate_richness(butter_melt_fraction: float) -> dict:
    """
    Estimates perceived richness from butter melt fraction.
    Reported even when phase violation is active because
    butter melting is not affected by the water-temperature conflict.
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
        "descriptor":            descriptor,
        "score":                 round(score, 3),
        "basis":                 "butter_melt_fraction",
        "input_value":           round(butter_melt_fraction, 4),
        "interpretation_status": "model rule, not sensory measurement",
    }


# ---------------------------------------------------------------------------
# Appearance
# ---------------------------------------------------------------------------

def estimate_appearance(
    denaturation_fraction: float,
    water_fraction_remaining: float,
) -> dict:
    """
    Estimates visual appearance from denaturation and moisture.

    Color is estimated from denaturation only.
    Maillard browning is not yet modeled — color cannot
    include brown or golden tones until that model is added.

    Surface description is based on moisture retention.
    """
    if denaturation_fraction < 0.3:
        color = "translucent, raw yellow"
    elif denaturation_fraction < 0.7:
        color = "pale yellow, partially set"
    else:
        color = "opaque pale yellow"

    if water_fraction_remaining > 0.85:
        surface = "glossy, wet surface"
    elif water_fraction_remaining > 0.65:
        surface = "slightly glossy"
    else:
        surface = "matte, dry surface"

    return {
        "color":   color,
        "surface": surface,
        "notes": [
            "Maillard browning not modeled — no golden or brown tones predicted.",
            "Curd size and structure not modeled.",
        ],
        "interpretation_status": "model rule, not sensory measurement",
    }


# ---------------------------------------------------------------------------
# Chef assessment
# ---------------------------------------------------------------------------

def generate_chef_assessment(
    texture:         dict,
    moisture:        dict,
    richness:        dict,
    phase_violation: bool,
    confidence:      dict,
) -> dict:
    """
    Generates a structured chef assessment.

    When phase violation is active, assessment is suppressed.
    Otherwise applies threshold rules to produce a service verdict.
    """
    if phase_violation:
        return {
            "verdict":    "suppressed",
            "suitability": None,
            "note": (
                "Assessment suppressed. Phase-state violation active. "
                "Fit the heating-rate parameter before interpreting "
                "chef assessment."
            ),
        }

    denat   = texture.get("input_value", 0.0)
    moist   = moisture.get("score", 0.0)
    rich    = richness.get("score", 0.0)

    issues  = []
    verdict = "acceptable"

    if denat > 0.90:
        issues.append("possibly overcooked — full protein set reached")
        verdict = "overcooked"
    elif denat > 0.75:
        verdict = "well cooked"
    elif denat > 0.50:
        verdict = "medium cooked"
    else:
        issues.append("undercooked — protein not fully set")
        verdict = "undercooked"

    if moist < 0.5:
        issues.append("dry texture — significant moisture lost")

    if rich >= 0.7:
        suitability = "suitable for standard service"
    else:
        suitability = "butter flavor may be insufficient for rich egg dishes"

    return {
        "verdict":     verdict,
        "suitability": suitability,
        "issues":      issues,
        "confidence":  confidence["label"],
        "note": (
            "Chef assessment uses fixed threshold rules. "
            "Not validated against professional tasting panels."
        ),
    }


# ---------------------------------------------------------------------------
# Suppressed dimension
# ---------------------------------------------------------------------------

def _unreliable_dimension(reason: str) -> dict:
    return {
        "score":                 None,
        "descriptor":            PHASE_INVALID_DESCRIPTOR,
        "basis":                 "suppressed",
        "interpretation_status": reason,
    }


# ---------------------------------------------------------------------------
# Chef note
# ---------------------------------------------------------------------------

def generate_chef_note(
    texture:            dict,
    moisture:           dict,
    richness:           dict,
    physics_confidence: dict,
    phase_violation:    bool,
) -> str:
    if phase_violation:
        return (
            "Sensory description suppressed. "
            "The simulated temperature exceeds the boiling region "
            "while substantial water remains (W-PHASE-001). "
            "Fit the heating-rate parameter before interpreting "
            "any sensory output."
        )

    score = physics_confidence["score"]
    if score < 0.25:
        prefix = "Speculative. | "
    elif score < 0.50:
        prefix = "Indicative only. | "
    else:
        prefix = ""

    parts = []

    if texture.get("descriptor") and texture.get("score") is not None:
        parts.append(texture["descriptor"])

    if moisture.get("score") is not None:
        if moisture["score"] >= 0.7:
            parts.append("good moisture retention")
        else:
            parts.append("reduced moisture")

    if richness.get("score") is not None:
        if richness["score"] >= 0.7:
            parts.append("rich buttery flavor")
        elif richness["score"] >= 0.4:
            parts.append("noticeable butter")
        else:
            parts.append("light butter presence")

    return (
        prefix + ", ".join(parts) + "."
        if parts
        else "No sensory description available."
    )


# ---------------------------------------------------------------------------
# Main sensory report function
# ---------------------------------------------------------------------------

def generate_sensory_report(simulation_result: dict) -> dict:
    """
    Generates a full sensory report from a simulation result dict.

    Structure:
      sensory_model_version
      interpretation_status
      phase_violation_active
      physics_confidence        — score, label, reason list
      dimensions
        texture                 — descriptor, sub_dimensions, basis
        moisture                — descriptor, score, basis
        richness                — descriptor, score, basis
        appearance              — color, surface (when not suppressed)
      chef_note                 — plain-language summary
      chef_assessment           — verdict, suitability, issues
      not_yet_modeled           — explicit list of missing physics

    Must not be presented as a taste measurement.
    """
    outputs         = simulation_result["outputs"]
    initial         = simulation_result["initial_state"]
    phase_violation = _phase_violation_active(simulation_result)
    physics_conf    = calculate_physics_confidence(simulation_result)

    suppression_reason = (
        "suppressed — phase-state violation active. "
        "Temperature exceeds boiling region while water remains. "
        "Fit heating-rate parameter before using sensory output."
    )

    # Texture and moisture suppressed under phase violation
    if phase_violation:
        texture  = _unreliable_dimension(suppression_reason)
        moisture = _unreliable_dimension(suppression_reason)
    else:
        texture = estimate_texture(
            denaturation_fraction=outputs["protein_denaturation_fraction"],
        )
        moisture = estimate_moisture(
            remaining_water_mass_g=outputs["remaining_water_mass_g"],
            initial_water_mass_g=initial["water_mass_g"],
        )

    # Richness always reported
    richness = estimate_richness(
        butter_melt_fraction=outputs["butter_melt_fraction"],
    )

    # Appearance suppressed under phase violation
    if phase_violation:
        appearance = _unreliable_dimension(suppression_reason)
    else:
        water_frac = (
            outputs["remaining_water_mass_g"] / initial["water_mass_g"]
            if initial["water_mass_g"] > 0
            else 0.0
        )
        appearance = estimate_appearance(
            denaturation_fraction=outputs["protein_denaturation_fraction"],
            water_fraction_remaining=water_frac,
        )

    chef_note = generate_chef_note(
        texture=texture,
        moisture=moisture,
        richness=richness,
        physics_confidence=physics_conf,
        phase_violation=phase_violation,
    )

    chef_assessment = generate_chef_assessment(
        texture=texture,
        moisture=moisture,
        richness=richness,
        phase_violation=phase_violation,
        confidence=physics_conf,
    )

    return {
        "sensory_model_version":  "0.1.2",
        "interpretation_status": (
            "model output derived from physics simulation. "
            "Not a sensory measurement. "
            "Not validated against human tasting panels."
        ),
        "phase_violation_active": phase_violation,
        "physics_confidence": physics_conf,
        "dimensions": {
            "texture":    texture,
            "moisture":   moisture,
            "richness":   richness,
            "appearance": appearance,
        },
        "chef_note":       chef_note,
        "chef_assessment": chef_assessment,
        "not_yet_modeled": [
            "browning and Maillard flavor",
            "aroma compounds",
            "saltiness from salt distribution",
            "temperature at serving",
            "visual color from browning or caramelization",
            "curd size and structure",
            "individual perception variability",
        ],
    }
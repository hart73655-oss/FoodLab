"""
models/perception.py
FoodLab v0.2.0

Perceptual Layer — Layer 1 of the Artificial Food Perception System.

Converts physical simulation outputs (Layer 0) into
perceptual signals that represent how the food might
be experienced across multiple sensory channels.

This is NOT a model of human taste.
It is a computational proxy that reasons about likely
perceptual qualities from physical measurements.

Sensory channels modeled:
  Taste-adjacent:  juiciness, tenderness, creaminess,
                   roastedness, bitterness, richness
  Surface:         crunch
  Visual:          colour, appearance

Not yet modeled:
  Sweetness (requires sugar concentration tracking)
  Saltiness (requires NaCl distribution model)
  Umami (requires glutamate release model)
  Sourness (requires organic acid formation)
  Aroma (requires volatile compound tracking)
  Retronasal aroma
  Trigeminal sensations (spice, cooling)
  Serving temperature effects
  Individual and cultural variation

Every dimension returns:
  score     float 0.0 to 1.0
  label     plain-language descriptor
  evidence  list of strings explaining why the score exists
  status    always "model_rule_not_validated"

The evidence field is what makes this explainable.
Instead of "juicy: 0.81", the system can say:
"This egg is predicted to be juicy because it retained
92% of its water and protein denaturation remained in
the tender range."

Scientific status:
  All conversion rules are model choices.
  None have been validated against human sensory panels.
  They represent a computational proxy, not measured perception.

Layer architecture:
  Layer 0  Physical Food State   (engine/simulate.py)
  Layer 1  Perceptual Conversion (models/perception.py)  ← this file
  Layer 2  Memory                (future)
  Layer 3  Preference            (future)
  Layer 4  Reasoning             (future)
  Layer 5  Recipe Generation     (future)
"""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALIDATION_STATUS = "model_rule_not_validated"

NOT_YET_MODELED = [
    "sweetness — requires sugar concentration tracking",
    "saltiness — requires NaCl distribution model",
    "umami — requires glutamate release model",
    "sourness — requires organic acid formation model",
    "aroma — requires volatile compound tracking",
    "retronasal aroma",
    "trigeminal sensations (spice heat, cooling, carbonation)",
    "serving temperature effects on perception",
    "individual human perception variability",
    "cultural and learned preference differences",
    "texture heterogeneity (curd size, layering)",
    "sound (sizzle, crunch acoustic signature)",
]


# ---------------------------------------------------------------------------
# Evidence builder
# ---------------------------------------------------------------------------

def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _build_dimension(
    score: float,
    label: str,
    evidence: list[str],
    basis: str,
    suppressed: bool = False,
    suppression_reason: str = "",
) -> dict:
    """
    Builds a standardised perceptual dimension dict.

    Every dimension has the same structure so downstream
    reasoning can treat them uniformly.
    """
    return {
        "score":    round(_clamp(score), 4),
        "label":    label,
        "evidence": evidence,
        "basis":    basis,
        "status":   VALIDATION_STATUS,
        "suppressed":         suppressed,
        "suppression_reason": suppression_reason,
    }


# ---------------------------------------------------------------------------
# Juiciness
# ---------------------------------------------------------------------------

def compute_juiciness(
    water_fraction: float,
    denaturation_fraction: float,
) -> dict:
    """
    Juiciness from water retention and protein structure.

    High water retention → juicy.
    Tight protein network (high denaturation) squeezes out water
    and reduces perceived juiciness even when water mass is retained.

    Assumptions:
      A-PC-001: Juiciness scales primarily with water fraction.
      A-PC-002: High denaturation reduces effective juiciness
                because protein network holds water less available
                to the palate.

    Ignores: fat-mediated moisture perception, serving temperature.
    """
    base_score     = water_fraction
    denat_penalty  = max(0.0, denaturation_fraction - 0.80) * 0.5
    score          = _clamp(base_score - denat_penalty)

    evidence = []

    if water_fraction > 0.85:
        evidence.append(
            f"High water retention ({water_fraction:.0%}) "
            "suggests good moisture."
        )
    elif water_fraction > 0.60:
        evidence.append(
            f"Moderate water retention ({water_fraction:.0%})."
        )
    else:
        evidence.append(
            f"Low water retention ({water_fraction:.0%}) "
            "suggests dryness."
        )

    if denaturation_fraction > 0.85:
        evidence.append(
            f"High protein denaturation ({denaturation_fraction:.0%}) "
            "tightens the protein network, reducing perceived juiciness."
        )
    elif denaturation_fraction > 0.60:
        evidence.append(
            f"Moderate denaturation ({denaturation_fraction:.0%}) "
            "provides some structure without excessive dryness."
        )

    if score > 0.85:
        label = "very juicy"
    elif score > 0.65:
        label = "juicy"
    elif score > 0.40:
        label = "slightly dry"
    else:
        label = "dry"

    return _build_dimension(
        score=score, label=label, evidence=evidence,
        basis="water_fraction adjusted for denaturation_fraction",
    )


# ---------------------------------------------------------------------------
# Tenderness
# ---------------------------------------------------------------------------

def compute_tenderness(denaturation_fraction: float) -> dict:
    """
    Tenderness from protein denaturation level.

    Peak tenderness occurs at moderate denaturation (0.55–0.75).
    Below: raw and unset.
    Above: firm, rubbery.

    Assumption:
      A-PC-003: Tenderness is a bell-curve function of denaturation.
    Ignores: connective tissue, fat marbling, mechanical texture.
    """
    if denaturation_fraction < 0.3:
        score = denaturation_fraction * 0.5
        label = "raw, unset"
        evidence = [
            f"Protein denaturation ({denaturation_fraction:.0%}) "
            "is below the threshold for visible setting.",
            "Food has not reached cooking temperature long enough.",
        ]
    elif denaturation_fraction < 0.60:
        score = 0.85
        label = "tender"
        evidence = [
            f"Protein denaturation ({denaturation_fraction:.0%}) "
            "is in the optimal range for soft, tender texture.",
            "Protein network is set but not overtightened.",
        ]
    elif denaturation_fraction < 0.85:
        score = 0.55
        label = "firm"
        evidence = [
            f"Protein denaturation ({denaturation_fraction:.0%}) "
            "has passed the tender range.",
            "Protein network is tightening, reducing tenderness.",
        ]
    else:
        score = 0.20
        label = "tough, rubbery"
        evidence = [
            f"Protein denaturation is near complete ({denaturation_fraction:.0%}).",
            "Protein network is fully set and contracted.",
            "Texture is likely firm and rubbery.",
        ]

    return _build_dimension(
        score=score, label=label, evidence=evidence,
        basis="protein_denaturation_fraction (bell curve)",
    )


# ---------------------------------------------------------------------------
# Creaminess
# ---------------------------------------------------------------------------

def compute_creaminess(
    water_fraction: float,
    fat_fraction: float,
    denaturation_fraction: float,
) -> dict:
    """
    Creaminess from moisture, fat, and protein structure interaction.

    Creamy texture requires:
      - Moderate to high water retention
      - Fat presence for mouthfeel
      - Moderate denaturation (not fully set)

    Assumption:
      A-PC-004: Creaminess is multiplicative across these factors.
                All three must be present for high creaminess.
    Ignores: emulsification state, fat crystal structure.
    """
    water_contribution = _clamp(water_fraction)
    fat_contribution   = _clamp(fat_fraction * 3.0)
    set_factor         = _clamp(1.0 - abs(denaturation_fraction - 0.55) * 2.0)

    score   = water_contribution * fat_contribution * set_factor
    evidence = []

    evidence.append(
        f"Water retention ({water_fraction:.0%}) "
        + ("contributes to creaminess." if water_fraction > 0.7
           else "limits creaminess.")
    )
    evidence.append(
        f"Fat presence (estimated fraction {fat_fraction:.2f}) "
        + ("provides mouthfeel." if fat_fraction > 0.1
           else "is insufficient for strong creaminess.")
    )
    if denaturation_fraction < 0.4 or denaturation_fraction > 0.75:
        evidence.append(
            f"Protein denaturation ({denaturation_fraction:.0%}) "
            "is outside the optimal range for creamy texture."
        )
    else:
        evidence.append(
            f"Protein denaturation ({denaturation_fraction:.0%}) "
            "is in the range that supports soft, creamy texture."
        )

    if score > 0.70:
        label = "very creamy"
    elif score > 0.45:
        label = "creamy"
    elif score > 0.25:
        label = "slightly creamy"
    else:
        label = "not creamy"

    return _build_dimension(
        score=score, label=label, evidence=evidence,
        basis="water × fat × denaturation_curve product",
    )


# ---------------------------------------------------------------------------
# Roastedness
# ---------------------------------------------------------------------------

def compute_roastedness(browning_index: float) -> dict:
    """
    Roasted flavor proxy from Maillard browning index.

    Higher browning → more Maillard reaction products →
    roasted, nutty, complex flavour notes.

    Note: This is a gross simplification.
    Real Maillard flavor involves hundreds of volatile compounds
    (pyrazines, furans, aldehydes, ketones) not yet tracked.

    Assumption:
      A-PC-005: Roastedness correlates monotonically with browning index.
    Ignores: specific compound profiles, temperature history,
             pH effects, precursor concentrations.
    """
    score    = browning_index
    evidence = []

    if browning_index < 0.05:
        label = "none"
        evidence.append(
            "Surface browning index is near zero. "
            "No significant Maillard reaction has occurred."
        )
    elif browning_index < 0.20:
        label = "faint"
        evidence.append(
            f"Light browning ({browning_index:.2f}) suggests "
            "early Maillard reaction products."
        )
        evidence.append(
            "Slight roasted or cooked notes possible."
        )
    elif browning_index < 0.45:
        label = "light roast"
        evidence.append(
            f"Moderate browning ({browning_index:.2f}) indicates "
            "active Maillard reaction."
        )
        evidence.append(
            "Nutty, lightly roasted flavour notes expected."
        )
    elif browning_index < 0.70:
        label = "medium roast"
        evidence.append(
            f"Significant browning ({browning_index:.2f}). "
            "Strong Maillard products."
        )
        evidence.append(
            "Rich roasted flavour. Risk of approaching burned territory."
        )
    else:
        label = "strong roast"
        evidence.append(
            f"Heavy browning ({browning_index:.2f}). "
            "Extensive Maillard reaction."
        )
        evidence.append(
            "Strong roasted flavor. May include bitter compounds."
        )

    return _build_dimension(
        score=_clamp(score), label=label, evidence=evidence,
        basis="browning_index (Maillard proxy)",
    )


# ---------------------------------------------------------------------------
# Bitterness from burning
# ---------------------------------------------------------------------------

def compute_bitterness_from_burn(burn_index: float) -> dict:
    """
    Burn bitterness from acrolein, char, and degradation products.

    Note: Bitterness has many other sources (coffee, dark chocolate,
    certain vegetables, phenolic compounds) not modeled here.
    This function models only burning-derived bitterness.

    Assumption:
      A-PC-006: Burn bitterness scales with burn_index.
    Ignores: all non-burn sources of bitterness.
    """
    score    = burn_index
    evidence = []

    if burn_index < 0.05:
        label = "none"
        evidence.append(
            "No significant burn index. "
            "Burning-derived bitterness is negligible."
        )
    elif burn_index < 0.25:
        label = "faint char"
        evidence.append(
            f"Low burn index ({burn_index:.2f}). "
            "Faint char notes may be detectable."
        )
    elif burn_index < 0.50:
        label = "noticeable bitterness"
        evidence.append(
            f"Moderate burn index ({burn_index:.2f}). "
            "Bitter compounds from thermal degradation."
        )
        evidence.append(
            "Acrolein and char compounds likely present."
        )
    elif burn_index < 0.75:
        label = "strong bitterness"
        evidence.append(
            f"High burn index ({burn_index:.2f}). "
            "Strong bitterness from significant burning."
        )
    else:
        label = "unpleasant, acrid"
        evidence.append(
            f"Very high burn index ({burn_index:.2f}). "
            "Food is likely unpalatable."
        )
        evidence.append(
            "Acrid, burnt flavour dominates."
        )

    return _build_dimension(
        score=_clamp(score), label=label, evidence=evidence,
        basis="burn_index (burn-derived bitterness only)",
    )


# ---------------------------------------------------------------------------
# Surface crunch
# ---------------------------------------------------------------------------

def compute_surface_crunch(
    browning_index: float,
    water_fraction: float,
) -> dict:
    """
    Surface crunch from browning and surface drying.

    Crunch requires:
      - Significant browning (surface transformation via Maillard)
      - Low surface water content (drying creates brittleness)

    Relevant for fried eggs, omelette edges, hash browns.
    Less relevant for scrambled eggs unless overdone.

    Assumption:
      A-PC-007: Crunch = browning × surface_dryness.
    Ignores: crust thickness, structural integrity, layering.
    """
    dryness = 1.0 - water_fraction
    score   = browning_index * dryness
    evidence = []

    evidence.append(
        f"Browning index ({browning_index:.2f}) "
        + ("provides surface transformation for crunch."
           if browning_index > 0.2
           else "is insufficient for meaningful crunch.")
    )
    evidence.append(
        f"Surface dryness ({dryness:.0%}) "
        + ("contributes to crunchiness."
           if dryness > 0.3
           else "— high moisture prevents crunch.")
    )

    if score < 0.05:
        label = "no crunch"
    elif score < 0.20:
        label = "slight crunch"
    elif score < 0.50:
        label = "crunchy"
    else:
        label = "very crunchy"

    return _build_dimension(
        score=_clamp(score), label=label, evidence=evidence,
        basis="browning_index × (1 - water_fraction)",
    )


# ---------------------------------------------------------------------------
# Richness
# ---------------------------------------------------------------------------

def compute_richness(butter_melt_fraction: float) -> dict:
    """
    Fat-mediated richness from butter melt fraction.

    Fully melted butter distributes evenly through the mixture,
    coating proteins and providing mouthfeel.

    Assumption:
      A-PC-008: Richness scales linearly with butter melt fraction.
    Ignores: other fat sources, emulsification state, cream content.
    """
    score    = butter_melt_fraction
    evidence = []

    if butter_melt_fraction > 0.90:
        label = "rich, buttery"
        evidence.append(
            f"Butter is fully melted ({butter_melt_fraction:.0%}). "
            "Fat is evenly distributed through the mixture."
        )
        evidence.append(
            "Strong mouthfeel and richness expected."
        )
    elif butter_melt_fraction > 0.60:
        label = "noticeable richness"
        evidence.append(
            f"Butter is substantially melted ({butter_melt_fraction:.0%}). "
            "Good fat distribution."
        )
    elif butter_melt_fraction > 0.30:
        label = "light richness"
        evidence.append(
            f"Butter is partially melted ({butter_melt_fraction:.0%}). "
            "Uneven fat distribution likely."
        )
    else:
        label = "minimal fat richness"
        evidence.append(
            f"Butter is mostly solid ({butter_melt_fraction:.0%}). "
            "Little fat has been released into the mixture."
        )

    return _build_dimension(
        score=_clamp(score), label=label, evidence=evidence,
        basis="butter_melt_fraction",
    )


# ---------------------------------------------------------------------------
# Visual perception
# ---------------------------------------------------------------------------

def compute_visual_appearance(
    browning_index: float,
    denaturation_fraction: float,
    water_fraction: float,
) -> dict:
    """
    Visual appearance from browning, denaturation, and moisture.

    Visual perception affects taste expectation before food
    is tasted. A golden-brown egg signals Maillard compounds
    and primes for roasted flavour.

    Dimensions estimated:
      colour       from browning and denaturation
      surface_sheen from water fraction
      set_appearance from denaturation

    Assumption:
      A-PC-009: Colour correlates with browning_index.
      A-PC-010: Surface sheen correlates with water_fraction.
    Ignores: actual light scattering, photography, CIE Lab colour.
    """
    evidence = []

    if browning_index < 0.05:
        if denaturation_fraction < 0.3:
            colour = "translucent, raw"
        elif denaturation_fraction < 0.7:
            colour = "pale yellow, partially set"
        else:
            colour = "opaque pale yellow"
    elif browning_index < 0.25:
        colour = "light golden"
    elif browning_index < 0.55:
        colour = "golden brown"
    else:
        colour = "dark brown"

    if water_fraction > 0.85:
        sheen = "glossy, moist surface"
        evidence.append(
            "High moisture gives a glossy, wet appearance."
        )
    elif water_fraction > 0.60:
        sheen = "slightly glossy"
    else:
        sheen = "matte, dry surface"
        evidence.append(
            "Low moisture gives a dry, matte appearance."
        )

    evidence.append(
        f"Browning index ({browning_index:.2f}) suggests "
        f"colour: {colour}."
    )
    evidence.append(
        f"Protein denaturation ({denaturation_fraction:.0%}) "
        + ("— food appears fully set."
           if denaturation_fraction > 0.80
           else "— food appears partially set.")
    )

    visual_score = _clamp(
        0.4
        + browning_index * 0.3
        + denaturation_fraction * 0.2
        + water_fraction * 0.1
    )

    return _build_dimension(
        score=visual_score,
        label=f"{colour}, {sheen}",
        evidence=evidence,
        basis="browning_index + denaturation_fraction + water_fraction",
    )


# ---------------------------------------------------------------------------
# Main perceptual profile generator
# ---------------------------------------------------------------------------

def generate_perceptual_profile(
    simulation_result: dict,
    fat_fraction: float = 0.15,
) -> dict:
    """
    Converts a complete simulation result into a full perceptual profile.

    This is the main entry point for Layer 1.

    Parameters
    ----------
    simulation_result : dict
        Output of engine.simulate.simulate().
    fat_fraction : float
        Estimated fat fraction of the mixture.
        Currently not computed from ingredient database.
        Future: derive automatically.

    Returns
    -------
    dict
        Structured perceptual profile with all dimensions,
        evidence for each score, confidence level,
        and explicit limitations.
    """
    out     = simulation_result["outputs"]
    sr      = simulation_result.get("sensory_report", {})
    initial = simulation_result["initial_state"]

    initial_water   = initial.get("water_mass_g", 1.0)
    remaining_water = out.get("remaining_water_mass_g", initial_water)
    water_fraction  = (
        remaining_water / initial_water
        if initial_water > 0
        else 0.0
    )

    denaturation     = out["protein_denaturation_fraction"]
    browning         = out["browning_index"]
    burn             = out["burn_index"]
    butter_melt      = out["butter_melt_fraction"]
    phase_violation  = len(simulation_result.get("phase_warnings", [])) > 0
    physics_conf     = sr.get("physics_confidence", {}).get("score", 0.0)

    suppression_reason = (
        "Phase-state violation active (W-PHASE-001). "
        "Physical outputs are not realistic. "
        "Perceptual conversion from invalid physics is suppressed."
        if phase_violation
        else ""
    )

    def maybe_suppress(dimension: dict) -> dict:
        if phase_violation:
            dimension["suppressed"]         = True
            dimension["suppression_reason"] = suppression_reason
        return dimension

    dimensions = {
        "juiciness":       maybe_suppress(
            compute_juiciness(water_fraction, denaturation)
        ),
        "tenderness":      maybe_suppress(
            compute_tenderness(denaturation)
        ),
        "creaminess":      maybe_suppress(
            compute_creaminess(water_fraction, fat_fraction, denaturation)
        ),
        "roastedness":     maybe_suppress(
            compute_roastedness(browning)
        ),
        "bitterness_burn": compute_bitterness_from_burn(burn),
        "richness":        compute_richness(butter_melt),
        "surface_crunch":  maybe_suppress(
            compute_surface_crunch(browning, water_fraction)
        ),
        "visual_appearance": maybe_suppress(
            compute_visual_appearance(browning, denaturation, water_fraction)
        ),
    }

    # Perceptual confidence
    if phase_violation or physics_conf < 0.25:
        perceptual_confidence = "very_low"
        perceptual_note = (
            "Physics warnings are active. "
            "Most perceptual dimensions are suppressed. "
            "Fit the heating-rate parameter before interpreting "
            "perceptual outputs."
        )
    elif physics_conf < 0.50:
        perceptual_confidence = "low"
        perceptual_note = (
            "Physics is unvalidated. "
            "Perceptual dimensions are speculative."
        )
    elif physics_conf < 0.75:
        perceptual_confidence = "moderate"
        perceptual_note = (
            "Physics has passed basic checks. "
            "Perceptual dimensions are model-derived proxies."
        )
    else:
        perceptual_confidence = "high"
        perceptual_note = (
            "Physics is validated. "
            "Perceptual dimensions are the best available estimates "
            "from the current model set."
        )

    # Natural language summary
    active_dims = {
        k: v for k, v in dimensions.items()
        if not v.get("suppressed", False)
    }

    summary_parts = []
    for name, dim in active_dims.items():
        if dim.get("score", 0) > 0.05:
            summary_parts.append(
                f"{dim['label']} {name.replace('_', ' ')}"
            )

    natural_language_summary = (
        "Perceptual profile suppressed due to physics violations."
        if phase_violation
        else (
            "Predicted profile: " + ", ".join(summary_parts) + "."
            if summary_parts
            else "No significant perceptual signals detected."
        )
    )

    return {
        "perception_model_version": "0.1.0",
        "layer":                    1,
        "layer_name":               "Perceptual Conversion",
        "perceptual_confidence":    perceptual_confidence,
        "perceptual_note":          perceptual_note,
        "physics_confidence_score": round(physics_conf, 3),
        "phase_violation_active":   phase_violation,
        "dimensions":               dimensions,
        "natural_language_summary": natural_language_summary,
        "not_yet_modeled":          NOT_YET_MODELED,
        "layer_architecture": {
            "Layer 0": "Physical Food State (engine/simulate.py)",
            "Layer 1": "Perceptual Conversion (models/perception.py) ← current",
            "Layer 2": "Memory (future)",
            "Layer 3": "Preference (future)",
            "Layer 4": "Reasoning (future)",
            "Layer 5": "Recipe Generation (future)",
        },
    }
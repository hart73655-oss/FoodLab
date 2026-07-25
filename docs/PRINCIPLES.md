# FoodLab Design Principles

These principles govern every decision in FoodLab.
When in doubt, return to them.

---

## Principle 1 — Physical Traceability

Every perceptual output must be traceable back to either:

  a) A measurable physical quantity from the simulation, or
  b) An explicitly documented assumption with a clear label.

If you cannot answer "where does this number come from?",
the feature is not ready.

Example — acceptable:
  juiciness = f(water_fraction, denaturation_fraction)
  Basis: water_fraction from mass tracking,
         denaturation_fraction from protein model.
  Documented assumptions: A-PC-001, A-PC-002.

Example — not acceptable:
  sweetness = 0.6
  No physical basis. No documented assumption.
  Not ready.

---

## Principle 2 — Honest Uncertainty

Every output must carry its validation status.

  "model_rule_not_validated"
  means the rule exists and is documented,
  but has not been checked against human sensory data.

  "experimentally_fitted"
  means a parameter was fitted to real measurements,
  with source, RMSE, and replicate count recorded.

  "validated"
  means the output was compared to independent measurements
  and found to be within a documented error range.

Never remove a validation status field.
Never upgrade a status without evidence.

---

## Principle 3 — Suppression Over Fabrication

When the physics is invalid or outside its declared domain,
suppress the perceptual output rather than reporting it.

A suppressed output with an honest explanation is more
useful than a confident wrong answer.

Example:
  Phase violation active (W-PHASE-001).
  Temperature exceeds boiling while water remains.
  Juiciness: SUPPRESSED.
  Reason: physical inputs are not realistic.

---

## Principle 4 — Explainability Is Mandatory

Every perceptual dimension must return evidence:
a list of plain-language statements explaining
why the score is what it is.

The AI must be able to say:
  "This egg is predicted to be juicy because it retained
   92% of its water and protein denaturation remained
   in the tender range (0.55–0.75)."

Not just:
  "juiciness: 0.82"

---

## Principle 5 — One Layer At A Time

Do not implement Layer N+1 until Layer N is producing
meaningful, validated outputs.

  Layer 0  Physics           — implemented
  Layer 0.5  Chemistry       — future (stub exists)
  Layer 1  Perception        — implemented, unvalidated
  Layer 2  Memory            — future
  Layer 3  Preference        — future
  Layer 4  Reasoning         — future

Each layer has a clear dependency on the previous one.
Building Layer 3 before Layer 1 is validated produces a
confident but unreliable system.

---

## Principle 6 — Narrow Before Broad

v1.0 is one ingredient, one cooking method, solved well.

Not:
  All ingredients.
  All cooking methods.
  All layers.

The question v1.0 answers:

  "Can FoodLab predict a believable, explainable
   perceptual profile for an egg under different
   cooking conditions?"

If yes, everything else grows from that foundation.
If no, the foundation needs work before expanding.

---

## Principle 7 — Calibration Before Expansion

Adding new perceptual features while the physics layer
uses placeholder parameters produces a sophisticated system
built on an uncertain foundation.

Priority order:
  1. Calibrate the physics model with real measurements.
  2. Validate perceptual outputs against cook judgment.
  3. Then add new features.

An unvalidated system with ten perceptual dimensions is
less valuable than a validated system with two.

---

## Principle 8 — Document What Is Missing

Every model must declare what it ignores.

A "not_yet_modeled" list is not an admission of failure.
It is scientific honesty.

Future contributors know exactly where to contribute.
Current users know exactly what to trust.

---

## Principle 9 — Independent Layers

Each layer must be callable independently.

  physics    = simulate(recipe, ...)
  perception = generate_perceptual_profile(physics)
  memory     = memory_layer.learn(perception)

No layer should import from a layer above it.
No layer should require all other layers to be present.

This makes testing, extension, and replacement of individual
layers possible without rebuilding the whole system.

---

## Principle 10 — The Benchmark Is The Validator

The most important test is not a unit test.

It is the comparison table:

  Egg at different conditions → FoodLab predictions
  → Reviewed by an experienced cook or food scientist
  → "Does this match what I would expect?"

Software tests verify that the code does what it says.
The benchmark verifies that what it says is meaningful.

Both are required. Neither replaces the other.
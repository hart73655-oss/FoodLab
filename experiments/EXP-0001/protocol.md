# FoodLab Heating Calibration Protocol
# Version: 1.1
# Experiment ID: EXP-0001
# Status: Ready for first calibration campaign

---

## Purpose

Estimate the heating_rate parameter k for the lumped
exponential heating model in models/mixture_heating.py.

The model equation is:

  T(t) = T_pan - (T_pan - T_0) * exp(-k * t)

where T_pan is treated as a single constant effective value
for the entire run.

---

## Important Limitation — Pan Temperature

Measuring the pan at 140°C immediately before adding cold eggs
does not mean the pan stays at 140°C. Its temperature will drop
when cold food is added and recover as the burner compensates.

This experiment uses a constant effective pan-temperature
approximation. The single measured pre-cooking value is used
as a fixed input to the fitter.

The fitted k will therefore absorb several real effects:

  - pan cooling after food is added
  - burner recovery rate
  - pan-to-food thermal contact resistance
  - stirring-induced mixing
  - pan geometry

This is acceptable for an empirical v0.1 model, but it means
the fitted value is valid only for similar equipment, settings,
and procedure. It must not be treated as a universal physical
constant.

Time-varying pan temperature recording and sequential
integration will be implemented in a later version.
Do not record a column of changing pan temperatures in
this experiment — the current fitter cannot correctly
interpret it.

---

## Equipment

| Item                    | Record Before Each Run               |
|-------------------------|--------------------------------------|
| Pan                     | material, diameter cm, depth cm      |
| Burner                  | type (induction/electric/gas), model |
| Burner setting          | exact dial position or watt setting  |
| Food thermometer        | model, stated accuracy ±°C           |
| Pan temperature method  | infrared thermometer (preferred)     |
|                         | or surface probe rated for metal     |
| Kitchen scale           | model, stated accuracy ±g            |
| Timer                   | stopwatch or phone, resolution 1 s   |
| Stirring tool           | silicone spatula, same tool each run |

---

## Initial Temperature Requirement

All replicates must start within a narrow temperature window.

  Target initial egg temperature : 20.0°C
  Maximum allowed deviation      : ±1.0°C between replicates

If R1 starts at 19.5°C and R2 at 21.0°C, the deviation exceeds
1.0°C. Do not proceed with R2 until the egg mixture returns to
within range.

Remove eggs from the refrigerator at least 30 minutes before
each run. Measure actual temperature at t=0 and record it.

The fitting tool currently uses one shared --initial-temp value
for all replicates. Keeping starting temperatures within ±1°C
makes this approximation reasonable.

---

## Fixed Parameters Per Run

| Parameter               | Target Value      | Record Actual    |
|-------------------------|-------------------|------------------|
| Egg mass (beaten whole) | 100.0 g           | ______ g         |
| Butter mass             | 10.0 g            | ______ g         |
| Salt mass               | 1.0 g             | ______ g         |
| Initial egg temperature | 20.0°C ± 1.0°C    | ______ °C        |
| Target pan temperature  | ______ °C         | ______ °C        |
| Probe position          | center, mid-depth | fixed each run   |
| Measurement interval    | every 30 seconds  | fixed            |
| Stirring interval       | every 15 seconds  | fixed            |

Choose one pan temperature and use it for all three replicates.
A value between 130°C and 160°C is typical for medium heat.

---

## Stirring and Measurement Schedule

Stirring and measurement occur on independent schedules.

Stirring occurs every 15 seconds.
Measurements occur every 30 seconds.
At 30-second marks both happen — record first, then stir.

  t =  15s : stir only
  t =  30s : record, then stir
  t =  45s : stir only
  t =  60s : record, then stir
  t =  75s : stir only
  t =  90s : record, then stir
  ... and so on

Stirring:
  3 slow folds with the spatula
  Return probe to center mid-depth after every fold
  Do not change technique between replicates

Measurements:
  Read food temperature after probe has settled
  Do not lift probe out of the mixture to read it

---

## Stopping Rule

Stop whichever occurs first:

  1. Food temperature reaches 88°C
  2. Visible surface drying begins
  3. 4 minutes (240 seconds) elapsed

Record the actual stop reason in metadata.

If a stopping condition occurs between scheduled measurements,
record an additional final row using the actual stop time and
measured food temperature. Do not leave the final measurement
empty.

Leave all subsequent scheduled rows empty in the CSV.
Do not invent or interpolate missing values.

---

## Procedure Per Run

Step 1
  Weigh the empty pan and record its mass as empty_pan_mass_g.

Step 2
  Weigh the egg mixture and record as egg_mass_g.
  Weigh the butter and record as butter_mass_g.
  Weigh the salt and record as salt_mass_g.
  Calculate:
    initial_ingredient_mass_g = egg_mass_g + butter_mass_g + salt_mass_g

Step 3
  Measure and record the egg mixture temperature.
  Confirm it is within ±1.0°C of 20.0°C.
  If not, wait and re-measure before continuing.

Step 4
  Heat the empty pan to the target pan temperature.
  Measure pan temperature using infrared thermometer or
  rated surface probe.
  Record as measured_pan_temp_c.
  This value will be used as the constant effective
  pan temperature in the fitter.

Step 5
  Add butter to the heated pan.
  Allow it to melt completely.
  Do not start the timer yet.

Step 6
  Add the egg mixture.
  Start the timer immediately.
  Insert the probe to center mid-depth of the mixture.

Step 7
  Record at t = 0 seconds:
    food_temp_c  (initial egg temperature)
    notes        (e.g. probe position, pan appearance)

Step 8
  Continue the stirring schedule independently:

    At 15, 45, 75, 105... seconds:
      Apply 3 slow folds.

    At 30, 60, 90, 120... seconds:
      Record elapsed time and food temperature.
      Then apply 3 slow folds.

  Return the probe to center mid-depth after every fold.
  Note any timing or procedure deviations.

Step 9
  Stop at the stopping rule.
  If stopping occurs between scheduled measurement intervals,
  record an additional final row with the actual stop time
  and measured food temperature.
  Record stop reason in metadata.

Step 10
  Weigh pan and remaining food together.
  Record as final_pan_and_food_mass_g.
  Calculate:
    final_food_mass_g = final_pan_and_food_mass_g - empty_pan_mass_g
    apparent_mass_loss_g = initial_ingredient_mass_g - final_food_mass_g

  Note that apparent_mass_loss_g includes:
    water evaporation  (what the model predicts)
    food on spatula    (not modeled)
    food stuck to pan  (not modeled)
    material on probe  (not modeled)

  Record these limitations in notes.

---

## CSV Format

Save each replicate as:

  experiments/EXP-0001-R1/temperatures.csv
  experiments/EXP-0001-R2/temperatures.csv
  experiments/EXP-0001-R3/temperatures.csv

Columns:

  time_sec      integer, seconds from t=0
  food_temp_c   measured food temperature in Celsius
  pan_temp_c    leave empty (constant pan mode for this protocol)
  notes         any deviation or observation

Example (experiment stopped at 88°C threshold at t=197s):

  time_sec,food_temp_c,pan_temp_c,notes
  0,20.1,,egg mixture added
  30,34.8,,
  60,51.2,,probe repositioned after fold
  90,63.7,,
  120,72.4,,
  150,79.8,,
  180,84.2,,
  197,88.0,,stopped at temperature threshold

The final measurement is always recorded, even when it occurs
between scheduled 30-second intervals.
Do not leave the stopping measurement empty.
Do not fill in food_temp_c for rows after stopping.
Do not invent or interpolate values.

---

## Metadata File

Complete before each run and save as:

  experiments/EXP-0001-R1/metadata.json

{
  "experiment_id": "EXP-0001-R1",
  "protocol_version": "1.1",
  "date": "",
  "operator": "",

  "equipment": {
    "pan_material": "",
    "pan_diameter_cm": null,
    "pan_depth_cm": null,
    "burner_type": "",
    "burner_model": "",
    "burner_setting": "",
    "thermometer_model": "",
    "thermometer_accuracy_c": null,
    "pan_temp_method": "",
    "scale_model": "",
    "scale_accuracy_g": null,
    "stirring_tool": "silicone spatula"
  },

  "masses": {
    "empty_pan_mass_g": null,
    "egg_mass_g": null,
    "butter_mass_g": null,
    "salt_mass_g": null,
    "initial_ingredient_mass_g": null,
    "final_pan_and_food_mass_g": null,
    "final_food_mass_g": null,
    "apparent_mass_loss_g": null
  },

  "temperatures": {
    "initial_egg_temp_c": null,
    "measured_pan_temp_c": null,
    "ambient_temp_c": null
  },

  "procedure": {
    "stirring_schedule": "3 slow folds every 15 seconds",
    "measurement_interval_sec": 30,
    "probe_position": "center mid-depth",
    "stop_reason": "",
    "actual_stop_time_sec": null
  },

  "limitations": [
    "Pan temperature measured once before food was added.",
    "Actual pan temperature during cooking is unknown.",
    "Fitted k absorbs pan cooling, burner recovery, and geometry.",
    "Apparent mass loss includes food on spatula and probe.",
    "Probe placement is manual and may shift between readings."
  ],

  "notes": ""
}

---

## Run Schedule

| Run | Purpose      | Notes                                     |
|-----|--------------|-------------------------------------------|
| R1  | Calibration  | First run, same settings for all three    |
| R2  | Calibration  | Different day preferred                   |
| R3  | Validation   | Do not use for fitting, hold out entirely |

---

## Calibration Command

After completing R1, R2, and R3:

  python tools/fit_heating_rate.py \
    --data experiments/EXP-0001-R1/temperatures.csv \
           experiments/EXP-0001-R2/temperatures.csv \
           experiments/EXP-0001-R3/temperatures.csv \
    --pan [measured_pan_temp_c] \
    --initial-temp 20.0 \
    --validation-replicate 3 \
    --bootstrap 1000 \
    --thermometer-accuracy [thermometer_accuracy_c] \
    --experiment-id EXP-0001 \
    --save-residuals results/EXP-0001-residuals.csv

Replace [measured_pan_temp_c] with the actual value recorded
in metadata. Use the same value for all three replicates if
pan temperature was kept consistent.

---

## Parameter Update Procedure

The tool will print a parameter block.

Open data/model_parameters.json.

Update only the heating_rate_per_second entry inside
mixture_heating_v0.1. Do not change any other block.

Then verify in this order:

  python main.py --no-save
  python -m pytest tests/ -v
  python main.py --output results/post-calibration-EXP-0001.json

Open the saved JSON and confirm:

  "status": "fitted"

inside mixture_heating_v0.1.heating_rate_per_second.

If status still reads "unfitted_placeholder", the file was
not saved correctly before re-running.

---

## Known State Before This Experiment

The tested software pipeline executes consistently and passes
its current automated checks. The model has not yet been
experimentally validated. This experiment begins that process.

Known computationally:
  Mass accounting is internally consistent.
  Warnings fire at the correct conditions.
  Sensory output is suppressed when physics is invalid.
  Calibration tools are ready to accept real data.

Not yet known:
  Whether the exponential model fits real heating data.
  Whether the fitted k is stable across replicates.
  Whether denaturation thresholds match real eggs.
  Whether the evaporation model matches real mass loss.
  Whether sensory descriptors match real outcomes.

---

## What This Experiment Does Not Validate

  Protein denaturation model
  Water evaporation model
  Sensory descriptors
  Boiling transition behavior
  Egg white vs yolk differences

Those require separate experimental campaigns after
heating calibration is complete.
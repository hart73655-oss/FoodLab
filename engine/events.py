"""
engine/events.py
FoodLab v0.1.7

Milestone event detection for simulation history.

An event is a named moment when a tracked quantity crosses
a threshold for the first time during a simulation.

Events are detected by scanning the TimeStep history after
the simulation loop completes. They are not generated during
the loop itself, which keeps the simulation core simple.

Events are informational only. They do not modify state.

Available events:
  BUTTER_MELTED           butter_melt_fraction >= 0.99
  DENATURATION_BEGINS     protein_denaturation >= 0.05
  DENATURATION_COMPLETE   protein_denaturation >= 0.99
  STICKINESS_MODERATE     stickiness_index >= 0.30
  STICKINESS_HIGH         stickiness_index >= 0.55
  BROWNING_BEGINS         browning_index >= 0.05
  BROWNING_MODERATE       browning_index >= 0.35
  BROWNING_DARK           browning_index >= 0.55
  BURN_RISK_LOW           burn_index >= 0.05
  BURN_RISK_MODERATE      burn_index >= 0.25
  BOILING_REGION_ENTERED  food_temp_c > 100.0 (with water present)
  EVAPORATION_BEGINS      food_temp_c >= 60.0

Thresholds are documented model choices, not validated standards.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from engine.state import TimeStep


# ---------------------------------------------------------------------------
# Event dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SimulationEvent:
    """
    A named moment detected in the simulation history.

    Fields
    ------
    event_id : str
        Unique identifier for the event type.
    elapsed_sec : float
        Time at which the event was first detected.
    description : str
        Plain-language description of what occurred.
    field : str
        The TimeStep field that triggered this event.
    threshold : float
        The threshold value that was crossed.
    observed_value : float
        The actual value at the detection step.
    severity : str
        "info", "warning", or "critical"
    """
    event_id:       str
    elapsed_sec:    float
    description:    str
    field:          str
    threshold:      float
    observed_value: float
    severity:       str = "info"

    def to_dict(self) -> dict:
        return {
            "event_id":       self.event_id,
            "elapsed_sec":    round(self.elapsed_sec, 1),
            "elapsed_min":    round(self.elapsed_sec / 60.0, 2),
            "description":    self.description,
            "field":          self.field,
            "threshold":      self.threshold,
            "observed_value": round(self.observed_value, 4),
            "severity":       self.severity,
        }

    def format_line(self) -> str:
        """Returns formatted one-line display string."""
        minutes = self.elapsed_sec / 60.0
        return (
            f"  {minutes:>5.1f} min  │  {self.description}"
        )


# ---------------------------------------------------------------------------
# Event definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EventDefinition:
    """
    Defines one detectable event.

    Fields
    ------
    event_id : str
    field : str
        Attribute name on TimeStep.
    threshold : float
        Value that must be reached or exceeded.
    description : str
    severity : str
    condition : Callable[[TimeStep], bool] | None
        Optional additional condition beyond the threshold.
        If None, only the threshold is checked.
    """
    event_id:    str
    field:       str
    threshold:   float
    description: str
    severity:    str = "info"
    condition:   Callable[[TimeStep], bool] | None = None


EVENT_DEFINITIONS: list[EventDefinition] = [
    EventDefinition(
        event_id="BUTTER_MELTED",
        field="butter_melt_fraction",
        threshold=0.99,
        description="Butter fully melted",
        severity="info",
    ),
    EventDefinition(
        event_id="EVAPORATION_BEGINS",
        field="food_temp_c",
        threshold=60.0,
        description="Food reached evaporation threshold (60°C)",
        severity="info",
    ),
    EventDefinition(
        event_id="DENATURATION_BEGINS",
        field="protein_denaturation",
        threshold=0.05,
        description="Protein denaturation begins (≥5%)",
        severity="info",
    ),
    EventDefinition(
        event_id="DENATURATION_HALF",
        field="protein_denaturation",
        threshold=0.50,
        description="Protein denaturation reached 50%",
        severity="info",
    ),
    EventDefinition(
        event_id="DENATURATION_COMPLETE",
        field="protein_denaturation",
        threshold=0.99,
        description="Protein denaturation complete (≥99%)",
        severity="info",
    ),
    EventDefinition(
        event_id="BOILING_REGION_ENTERED",
        field="food_temp_c",
        threshold=100.0,
        description="Food temperature entered boiling region (>100°C) — phase model not active",
        severity="warning",
        condition=lambda step: step.water_mass_g > 0.0,
    ),
    EventDefinition(
        event_id="STICKINESS_MODERATE",
        field="stickiness_index",
        threshold=0.30,
        description="Stickiness became moderate (≥0.30)",
        severity="info",
    ),
    EventDefinition(
        event_id="STICKINESS_HIGH",
        field="stickiness_index",
        threshold=0.55,
        description="Stickiness became high (≥0.55)",
        severity="warning",
    ),
    EventDefinition(
        event_id="BROWNING_BEGINS",
        field="browning_index",
        threshold=0.05,
        description="Surface browning began (≥0.05)",
        severity="info",
    ),
    EventDefinition(
        event_id="BROWNING_LIGHT",
        field="browning_index",
        threshold=0.15,
        description="Browning reached light level (≥0.15)",
        severity="info",
    ),
    EventDefinition(
        event_id="BROWNING_MODERATE",
        field="browning_index",
        threshold=0.35,
        description="Browning reached moderate level (≥0.35)",
        severity="info",
    ),
    EventDefinition(
        event_id="BROWNING_DARK",
        field="browning_index",
        threshold=0.55,
        description="Browning reached dark level (≥0.55)",
        severity="warning",
    ),
    EventDefinition(
        event_id="BURN_RISK_LOW",
        field="burn_index",
        threshold=0.05,
        description="Burn risk became low (≥0.05)",
        severity="warning",
    ),
    EventDefinition(
        event_id="BURN_RISK_MODERATE",
        field="burn_index",
        threshold=0.25,
        description="Burn risk became moderate (≥0.25)",
        severity="critical",
    ),
    EventDefinition(
        event_id="BURN_RISK_HIGH",
        field="burn_index",
        threshold=0.50,
        description="Burn risk became high (≥0.50)",
        severity="critical",
    ),
]


# ---------------------------------------------------------------------------
# Event detector
# ---------------------------------------------------------------------------

def detect_events(history: list[TimeStep]) -> list[SimulationEvent]:
    """
    Scans the timestep history and returns all detected events
    in chronological order.

    Each event is recorded only once — the first time its
    threshold is crossed.

    Parameters
    ----------
    history : list[TimeStep]
        Complete timestep history from SimulationResult.

    Returns
    -------
    list[SimulationEvent]
        Events sorted by elapsed_sec ascending.
    """
    if not history:
        return []

    detected:   list[SimulationEvent] = []
    triggered:  set[str]              = set()

    for step in history:
        for defn in EVENT_DEFINITIONS:
            if defn.event_id in triggered:
                continue

            value = getattr(step, defn.field, None)
            if value is None:
                continue

            threshold_crossed = value >= defn.threshold
            condition_met     = (
                defn.condition is None
                or defn.condition(step)
            )

            if threshold_crossed and condition_met:
                detected.append(SimulationEvent(
                    event_id=       defn.event_id,
                    elapsed_sec=    step.elapsed_sec,
                    description=    defn.description,
                    field=          defn.field,
                    threshold=      defn.threshold,
                    observed_value= value,
                    severity=       defn.severity,
                ))
                triggered.add(defn.event_id)

    return sorted(detected, key=lambda e: e.elapsed_sec)


# ---------------------------------------------------------------------------
# Event summary printer
# ---------------------------------------------------------------------------

def print_event_timeline(events: list[SimulationEvent]) -> None:
    """
    Prints a formatted event timeline to the terminal.
    """
    if not events:
        print("\n  EVENT TIMELINE")
        print("  " + "-" * 56)
        print("  No milestone events detected.")
        return

    print("\n  EVENT TIMELINE")
    print("  " + "-" * 56)
    print(f"  {'Time':>7}      Event")
    print("  " + "-" * 56)

    for event in events:
        severity_label = {
            "info":     "   ",
            "warning":  " ⚠ ",
            "critical": " ✖ ",
        }.get(event.severity, "   ")

        print(
            f"  {event.elapsed_sec / 60.0:>5.1f} min "
            f"{severity_label} {event.description}"
        )

    print("  " + "-" * 56)
    info_count     = sum(1 for e in events if e.severity == "info")
    warning_count  = sum(1 for e in events if e.severity == "warning")
    critical_count = sum(1 for e in events if e.severity == "critical")
    print(
        f"  {len(events)} events: "
        f"{info_count} info, "
        f"{warning_count} warning, "
        f"{critical_count} critical"
    )
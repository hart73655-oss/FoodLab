from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# TimeStep
# ---------------------------------------------------------------------------

@dataclass
class TimeStep:
    elapsed_sec:              float
    food_temp_c:              float
    effective_surface_temp_c: float
    water_mass_g:             float
    total_mass_g:             float
    total_water_loss_g:       float         
    butter_melt_fraction:     float
    protein_denaturation:     float
    browning_index:           float
    burn_index:               float
    stickiness_index:         float
    evap_cooling_c:           float
    high_temp_exposure_sec:   float

    def to_dict(self) -> dict:
        return {
            "elapsed_sec":              round(self.elapsed_sec, 1),
            "food_temp_c":              round(self.food_temp_c, 3),
            "effective_surface_temp_c": round(self.effective_surface_temp_c, 3),
            "water_mass_g":             round(self.water_mass_g, 3),
            "total_mass_g":             round(self.total_mass_g, 3),
            "total_water_loss_g":       round(self.total_water_loss_g, 3), 
            "butter_melt_fraction":     round(self.butter_melt_fraction, 4),
            "protein_denaturation":     round(self.protein_denaturation, 4),
            "browning_index":           round(self.browning_index, 4),
            "burn_index":               round(self.burn_index, 4),
            "stickiness_index":         round(self.stickiness_index, 4),
            "evap_cooling_c":           round(self.evap_cooling_c, 4),
            "high_temp_exposure_sec":   round(self.high_temp_exposure_sec, 1),
        }


# ---------------------------------------------------------------------------
# SimulationState
# ---------------------------------------------------------------------------

@dataclass
class SimulationState:
    """
    Mutable physical state of the food mixture at one instant.
    All models read from and write to this object.
    """

    food_temp_c:                   float
    effective_surface_temp_c:      float = 0.0
    cumulative_evap_cooling_c:     float = 0.0

    total_mass_g:                  float = 0.0
    water_mass_g:                  float = 0.0
    initial_water_mass_g:          float = 0.0
    total_water_loss_g:            float = 0.0

    butter_melt_fraction:          float = 0.0
    protein_denaturation_fraction: float = 0.0

    browning_index:                float = 0.0
    burn_index:                    float = 0.0
    stickiness_index:              float = 0.0

    high_temp_exposure_sec:        float = 0.0
    elapsed_sec:                   float = 0.0

    @property
    def water_fraction(self) -> float:
        if self.initial_water_mass_g <= 0.0:
            return 0.0
        return max(0.0, self.water_mass_g / self.initial_water_mass_g)

    def snapshot(self) -> TimeStep:
        return TimeStep(
            elapsed_sec=              self.elapsed_sec,
            food_temp_c=              self.food_temp_c,
            effective_surface_temp_c= self.effective_surface_temp_c,
            water_mass_g=             self.water_mass_g,
            total_mass_g=             self.total_mass_g,
            total_water_loss_g=       self.total_water_loss_g,    
            butter_melt_fraction=     self.butter_melt_fraction,
            protein_denaturation=     self.protein_denaturation_fraction,
            browning_index=           self.browning_index,
            burn_index=               self.burn_index,
            stickiness_index=         self.stickiness_index,
            evap_cooling_c=           self.cumulative_evap_cooling_c,
            high_temp_exposure_sec=   self.high_temp_exposure_sec,
        )


# ---------------------------------------------------------------------------
# SimulationResult
# ---------------------------------------------------------------------------

@dataclass
class SimulationResult:
    """
    Complete output of one simulation run.
    """

    simulation_id:   str            = field(
        default_factory=lambda: str(uuid.uuid4())
    )
    timestamp:       str            = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    recipe_id:       str            = ""
    model_version:   str            = "0.1.7"

    inputs:          dict           = field(default_factory=dict)
    initial_state:   dict           = field(default_factory=dict)
    outputs:         dict           = field(default_factory=dict)

    warnings:        list[dict]     = field(default_factory=list)
    domain_warnings: list[dict]     = field(default_factory=list)
    phase_warnings:  list[dict]     = field(default_factory=list)
    assumptions:     list[str]      = field(default_factory=list)

    sensory_report:  dict           = field(default_factory=dict)
    events:          list[dict]     = field(default_factory=list)
    history:         list[TimeStep] = field(default_factory=list)
    metadata:        dict           = field(default_factory=dict)

    # -----------------------------------------------------------------------
    # Convenience accessors
    # -----------------------------------------------------------------------

    @property
    def final_temperature_c(self) -> float:
        return self.outputs.get("estimated_final_temperature_c", 0.0)

    @property
    def final_mass_g(self) -> float:
        return self.outputs.get("estimated_final_mass_g", 0.0)

    @property
    def browning_index(self) -> float:
        return self.outputs.get("browning_index", 0.0)

    @property
    def burn_index(self) -> float:
        return self.outputs.get("burn_index", 0.0)

    @property
    def confidence_score(self) -> float:
        return (
            self.sensory_report
            .get("physics_confidence", {})
            .get("score", 0.0)
        )

    @property
    def total_warning_count(self) -> int:
        return (
            len(self.warnings)
            + len(self.domain_warnings)
            + len(self.phase_warnings)
        )

    # -----------------------------------------------------------------------
    # History analysis
    # -----------------------------------------------------------------------

    def temperature_at(self, elapsed_sec: float) -> float | None:
        if not self.history:
            return None
        times = [s.elapsed_sec for s in self.history]
        if elapsed_sec < times[0] or elapsed_sec > times[-1]:
            return None
        for i in range(len(self.history) - 1):
            t0 = self.history[i].elapsed_sec
            t1 = self.history[i + 1].elapsed_sec
            if t0 <= elapsed_sec <= t1:
                frac = (elapsed_sec - t0) / (t1 - t0) if t1 > t0 else 0.0
                return (
                    self.history[i].food_temp_c * (1.0 - frac)
                    + self.history[i + 1].food_temp_c * frac
                )
        return self.history[-1].food_temp_c

    def max_temperature_c(self) -> float:
        if not self.history:
            return 0.0
        return max(s.food_temp_c for s in self.history)

    def max_surface_temp_c(self) -> float:
        if not self.history:
            return 0.0
        return max(s.effective_surface_temp_c for s in self.history)

    def browning_onset_time_sec(self, threshold: float = 0.05) -> float | None:
        for step in self.history:
            if step.browning_index >= threshold:
                return step.elapsed_sec
        return None

    def ascii_history_plot(
        self,
        field: str = "food_temp_c",
        width: int = 50,
        height: int = 10,
    ) -> str:
        if not self.history:
            return "  No history recorded."

        values = [getattr(step, field, None) for step in self.history]
        values = [v for v in values if v is not None]

        if not values:
            return f"  Field '{field}' not found in history."

        v_min = min(values)
        v_max = max(values)
        v_rng = v_max - v_min if v_max > v_min else 1.0

        t_min = self.history[0].elapsed_sec
        t_max = self.history[-1].elapsed_sec
        t_rng = t_max - t_min if t_max > t_min else 1.0

        grid = [[" "] * width for _ in range(height)]

        for step, value in zip(self.history, values):
            col = int((step.elapsed_sec - t_min) / t_rng * (width - 1))
            row = int((v_max - value) / v_rng * (height - 1))
            col = max(0, min(width - 1, col))
            row = max(0, min(height - 1, row))
            grid[row][col] = "●"

        lines = [f"\n  {field} over time"]
        lines.append(f"  {v_max:>8.2f} ┐")
        for line in grid:
            lines.append(f"  {'':>8} │" + "".join(line))
        lines.append(f"  {v_min:>8.2f} ┘")
        lines.append(f"  {'':>10}" + "─" * width)
        lines.append(
            f"  {'':>10}{t_min:.0f}s"
            + " " * (width - 10)
            + f"{t_max:.0f}s"
        )
        return "\n".join(lines)

    # -----------------------------------------------------------------------
    # Serialisation
    # -----------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "simulation_id":   self.simulation_id,
            "timestamp":       self.timestamp,
            "recipe_id":       self.recipe_id,
            "model_version":   self.model_version,
            "inputs":          self.inputs,
            "initial_state":   self.initial_state,
            "outputs":         self.outputs,
            "warnings":        self.warnings,
            "domain_warnings": self.domain_warnings,
            "phase_warnings":  self.phase_warnings,
            "assumptions":     self.assumptions,
            "sensory_report":  self.sensory_report,
            "events":          self.events,
            "metadata":        self.metadata,
            "history":         [s.to_dict() for s in self.history],
        }

    @property
    def summary_line(self) -> str:
        return (
            f"[{self.simulation_id[:8]}] "
            f"{self.recipe_id} | "
            f"T={self.final_temperature_c:.1f}°C | "
            f"Browning={self.browning_index:.2f} | "
            f"Warnings={self.total_warning_count} | "
            f"Confidence={self.confidence_score:.2f} | "
            f"Events={len(self.events)}"
        )
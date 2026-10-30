"""F13.1 / F13.3 Daily energy balance: burned = baseline + exercise, balance = eaten - burned.

Pure (ADR 0004): plain integers in, a result with an `explanation` out. The caller supplies the
baseline of the `Targets` row valid on the day, so later target changes never alter a past day.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EnergyInputs:
    eaten_kcal: int
    baseline_kcal: int
    training_kcal: int
    activities_kcal: int


@dataclass(frozen=True)
class EnergyResult:
    burned_kcal: int
    balance_kcal: int
    explanation: str


def day_balance(inputs: EnergyInputs) -> EnergyResult:
    """burned = baseline + training + extra activities; balance = eaten - burned (F13.1)."""
    burned = inputs.baseline_kcal + inputs.training_kcal + inputs.activities_kcal
    balance = inputs.eaten_kcal - burned
    explanation = (
        f"burned {burned} kcal = baseline {inputs.baseline_kcal} + training "
        f"{inputs.training_kcal} + activities {inputs.activities_kcal}; "
        f"balance {balance} kcal = eaten {inputs.eaten_kcal} - burned {burned} (estimated)"
    )
    return EnergyResult(burned_kcal=burned, balance_kcal=balance, explanation=explanation)

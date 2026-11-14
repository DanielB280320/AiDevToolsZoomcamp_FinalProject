import type { CalendarDay } from "../../api/calendar";

/** The month's figures up to `today` (D103). `null` = nothing to average yet. */
export interface MonthKpis {
  /** Workouts finished, of those planned on days up to today. */
  sessionsDone: number;
  sessionsPlanned: number;
  /** Workouts still planned after today. */
  sessionsUpcoming: number;
  sessionsMissed: number;
  /** Mean completion (0-1, F10.2) of the finished workouts. */
  avgCompletion: number | null;
  mealsEaten: number;
  mealsPlanned: number;
  /** Planned meals eaten or adjusted ÷ planned meals (F12.2) over the days up to today. */
  mealsRatio: number | null;
  /** Mean estimated kcal eaten on the days with something logged. */
  avgEatenKcal: number | null;
  daysWithMeals: number;
}

/**
 * Figures of one month from its calendar days (the days of the month only, not the grid's leading
 * and trailing days). Only days up to `today` count, so a month in progress is not diluted by days
 * that have not happened; a future month has nothing to show.
 */
export function monthKpis(days: CalendarDay[], today: string): MonthKpis {
  const past = days.filter((d) => d.date <= today);
  const withWorkout = past.filter((d) => d.training_status !== "rest");
  const done = withWorkout.filter((d) => d.training_status === "done");
  const completions = done.map((d) => d.training_completion).filter((c): c is number => c !== null);
  const mealsPlanned = past.reduce((sum, d) => sum + d.planned_meal_count, 0);
  const mealsEaten = past.reduce((sum, d) => sum + d.eaten_meal_count, 0);
  const fed = past.filter((d) => d.energy.eaten.kcal > 0);
  return {
    sessionsDone: done.length,
    sessionsPlanned: withWorkout.length,
    sessionsUpcoming: days.filter((d) => d.date > today && d.training_status !== "rest").length,
    sessionsMissed: withWorkout.filter((d) => d.training_status === "missed").length,
    avgCompletion: completions.length > 0 ? completions.reduce((a, b) => a + b, 0) / completions.length : null,
    mealsEaten,
    mealsPlanned,
    mealsRatio: mealsPlanned > 0 ? mealsEaten / mealsPlanned : null,
    avgEatenKcal: fed.length > 0 ? Math.round(fed.reduce((sum, d) => sum + d.energy.eaten.kcal, 0) / fed.length) : null,
    daysWithMeals: fed.length,
  };
}

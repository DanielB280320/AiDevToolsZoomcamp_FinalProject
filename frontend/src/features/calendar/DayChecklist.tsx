import { useTranslation } from "react-i18next";

import { useAthleteProfile } from "../../api/athlete";
import type { DayView } from "../../api/calendar";
import { usePendingSuggestions } from "../../api/suggestions";
import { ChecklistIcon, TargetIcon } from "../../components/icons";
import type { UnitSystem } from "../../lib/units";
import { ProgressKpis } from "./ProgressKpis";

export const MEALS_SECTION_ID = "today-meals";
export const TRAINING_SECTION_ID = "today-training";
export const SUGGESTIONS_SECTION_ID = "today-suggestions";

/** State glyphs: shown next to a text label, so they are hidden from assistive technology. */
const GLYPH = { done: "✓", pending: "○" } as const;

type Item = {
  key: "meals" | "training" | "suggestions";
  done: boolean;
  text: string;
  /** Section of the page where the open item is handled. */
  target: string;
};

/**
 * What is done and what is still open on a day (D100): planned meals logged, the workout
 * finished, pending suggestions answered. The day is complete when nothing is open.
 * An item is listed only when it applies (no meals item on a day without planned meals).
 * Above the list it names the goal the athlete is working towards (from the profile) and
 * shows the progress figures.
 */
export function DayChecklist({
  day,
  athleteId,
  who,
  units,
  progressLink,
}: {
  day: DayView;
  athleteId: string;
  who: "athlete" | "coach";
  units: UnitSystem;
  /** Link under the progress figures to the full charts. */
  progressLink?: string;
}) {
  const { t } = useTranslation();
  const pending = usePendingSuggestions(athleteId);
  const goal = useAthleteProfile(athleteId).data?.goal;

  const items: Item[] = [];
  const planned = day.meals.length;
  if (planned > 0) {
    const logged = day.meals.filter((meal) => meal.log).length;
    items.push({
      key: "meals",
      done: logged === planned,
      text: t("calendar.today.checklist.meals", { logged, count: planned }),
      target: MEALS_SECTION_ID,
    });
  }
  const session = day.session;
  const training = !session ? "rest" : session.status === "in_progress" ? "inProgress" : session.status;
  items.push({
    key: "training",
    done: training === "rest" || training === "done",
    text: t(`calendar.today.checklist.training.${training}`),
    target: TRAINING_SECTION_ID,
  });
  if (pending.data) {
    const count = pending.data.length;
    items.push({
      key: "suggestions",
      done: count === 0,
      text: count === 0 ? t("calendar.today.checklist.suggestionsNone") : t("calendar.today.checklist.suggestions", { count }),
      target: SUGGESTIONS_SECTION_ID,
    });
  }

  const open = items.filter((item) => !item.done).length;
  const complete = open === 0;

  return (
    <section aria-labelledby="today-checklist" className="mt-6" data-testid="day-checklist">
      <h2 id="today-checklist" className="flex items-center gap-2 font-display text-step-2 font-bold">
        <ChecklistIcon className="size-7 text-spruce" />
        {t("calendar.today.checklist.title")}
      </h2>
      <p className="mt-1 text-step--1 text-slate" data-testid="section-description">
        {t(`calendar.today.checklist.about.${who}`)}
      </p>
      {goal && (
        <p className="mt-3 flex items-start gap-2" data-testid="day-goal">
          <TargetIcon className="mt-0.5 size-6 text-spruce" />
          <span>
            <span className="text-step--1 font-semibold uppercase text-slate">{t(`calendar.today.checklist.goal.${who}`)}</span>{" "}
            <span className="block font-display text-step-1 font-bold leading-tight">{t(`onboarding.goal.${goal}`)}</span>
            <span className="block text-step--1 text-slate">{t(`calendar.today.checklist.goal.detail.${goal}`)}</span>
          </span>
        </p>
      )}
      <ProgressKpis day={day} athleteId={athleteId} units={units} progressLink={progressLink} />
      <h3 className="mt-4 font-display text-step-1 font-bold">{t("calendar.today.checklist.pendingTitle")}</h3>
      <p
        data-testid="day-summary"
        data-complete={complete}
        className={`mt-2 border-l-4 px-3 py-2 font-semibold ${complete ? "border-spruce bg-spruce text-chalk" : "border-plate bg-white"}`}
      >
        <span aria-hidden="true">{complete ? GLYPH.done : GLYPH.pending}</span>{" "}
        {complete ? t("calendar.today.checklist.complete") : t("calendar.today.checklist.open", { count: open, total: items.length })}
      </p>
      <ul className="mt-1">
        {items.map((item) => (
          <li
            key={item.key}
            data-testid={`checklist-${item.key}`}
            data-done={item.done}
            className="flex min-h-11 items-center gap-3 border-b border-line py-1"
          >
            <span
              className={`inline-flex shrink-0 items-center gap-1 rounded-sm px-1.5 py-0.5 text-step--1 font-semibold leading-none ${
                item.done ? "bg-spruce text-chalk" : "border-2 border-iron bg-chalk text-iron"
              }`}
            >
              <span aria-hidden="true">{item.done ? GLYPH.done : GLYPH.pending}</span>
              {t(item.done ? "calendar.today.checklist.done" : "calendar.today.checklist.pending")}
            </span>
            {item.done ? (
              <span className="min-w-0 text-slate">{item.text}</span>
            ) : (
              <a href={`#${item.target}`} className="inline-flex min-h-11 min-w-0 items-center font-semibold text-iron underline underline-offset-4 hover:text-spruce">
                {item.text}
              </a>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

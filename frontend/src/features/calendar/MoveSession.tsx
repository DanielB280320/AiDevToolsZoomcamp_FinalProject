import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { type CalendarDay, useMoveSession } from "../../api/calendar";
import { DAY_FORMAT, formatDay } from "../../lib/calendarDates";
import { moveErrorKey } from "./problemMessage";

/**
 * "Move" control for one planned session (spec F9: within the same ISO week, one session per day,
 * today or later). `targets` are the week's free days the server would accept; the server stays the
 * authority and its refusal is shown if the calendar was stale.
 */
export function MoveSession({
  athleteId,
  day,
  targets,
}: {
  athleteId: string;
  day: CalendarDay;
  targets: string[];
}) {
  const { t, i18n } = useTranslation();
  const selectId = useId();
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState(targets[0] ?? "");
  const move = useMoveSession(athleteId);
  const name = day.training_day_name ?? "";

  if (targets.length === 0) return null;

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => {
          setTarget(targets[0] ?? "");
          setOpen(true);
        }}
        className="min-h-11 rounded-md border-2 border-iron px-4 font-semibold hover:bg-line"
      >
        {t("calendar.move.open")}
        <span className="sr-only"> {name}</span>
      </button>
    );
  }

  const submit = () => {
    if (move.isPending || !target) return;
    move.mutate({ from: day, to: target }, { onSuccess: () => setOpen(false) });
  };

  return (
    <div className="flex flex-col gap-2 border-l-4 border-plate pl-3">
      <label htmlFor={selectId} className="text-step--1 font-semibold">
        {t("calendar.move.label", { name })}
      </label>
      <select
        id={selectId}
        value={target}
        onChange={(e) => setTarget(e.target.value)}
        className="min-h-11 rounded-md border-2 border-iron bg-chalk px-2"
      >
        {targets.map((date) => (
          <option key={date} value={date}>
            {formatDay(date, i18n.language, DAY_FORMAT.weekdayDayMonth)}
          </option>
        ))}
      </select>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={submit}
          aria-disabled={move.isPending || undefined}
          className="min-h-11 rounded-md bg-spruce px-4 font-semibold text-chalk hover:bg-spruce-dark aria-disabled:opacity-75"
        >
          {move.isPending ? t("calendar.move.moving") : t("calendar.move.confirm")}
        </button>
        <button
          type="button"
          onClick={() => {
            move.reset();
            setOpen(false);
          }}
          className="min-h-11 rounded-md px-4 font-semibold text-spruce underline underline-offset-4"
        >
          {t("calendar.move.cancel")}
        </button>
      </div>
      {move.isError && (
        <p role="alert" className="text-step--1 text-alert">
          {t(`calendar.move.errors.${moveErrorKey(move.error)}`)}
        </p>
      )}
    </div>
  );
}

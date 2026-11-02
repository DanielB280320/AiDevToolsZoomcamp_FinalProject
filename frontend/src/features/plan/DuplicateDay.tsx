import { useState } from "react";
import { useTranslation } from "react-i18next";

import { WEEKDAYS, type Weekday } from "../../api/plan";
import { BUTTON, PRIMARY, SelectInput } from "./fields";

/**
 * "Duplicate day" (F8, D87): pick one target weekday; a target that already has content is replaced only
 * after the athlete confirms. `onCopy` changes the draft only; nothing is saved here.
 */
export function DuplicateDay({
  idPrefix,
  from,
  hasContent,
  onCopy,
}: {
  idPrefix: string;
  from: Weekday;
  hasContent: (weekday: Weekday) => boolean;
  onCopy: (weekday: Weekday) => void;
}) {
  const { t } = useTranslation();
  const targets = WEEKDAYS.filter((w) => w !== from);
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState<Weekday>(targets[0]!);
  const [confirming, setConfirming] = useState(false);
  const day = t(`plan.weekdayLong.${target}`);
  const close = () => {
    setOpen(false);
    setConfirming(false);
  };
  const copy = () => {
    onCopy(target);
    close();
  };

  if (!open) {
    return (
      <button type="button" className={`${BUTTON} mt-3`} onClick={() => setOpen(true)} aria-label={t("plan.duplicate.open", { weekday: t(`plan.weekdayLong.${from}`) })}>
        {t("plan.duplicate.button")}
      </button>
    );
  }
  return (
    <div className="mt-3 border-2 border-iron/30 p-3">
      <SelectInput
        id={`${idPrefix}-target`}
        label={t("plan.duplicate.target")}
        value={target}
        onChange={(w) => {
          setTarget(w as Weekday);
          setConfirming(false);
        }}
        options={targets.map((w) => ({ value: w, label: t(`plan.weekdayLong.${w}`) }))}
      />
      {confirming ? (
        <div role="alertdialog" aria-labelledby={`${idPrefix}-confirm-title`} className="mt-3 border-2 border-iron p-3">
          <p id={`${idPrefix}-confirm-title`} className="font-semibold">
            {t("plan.duplicate.confirmTitle", { weekday: day })}
          </p>
          <p className="mt-1">{t("plan.duplicate.confirmBody", { weekday: day })}</p>
          <div className="mt-3 flex flex-wrap gap-3">
            <button type="button" className={PRIMARY} onClick={copy}>
              {t("plan.duplicate.confirm", { weekday: day })}
            </button>
            <button type="button" className={BUTTON} onClick={close}>
              {t("plan.cancel")}
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-3 flex flex-wrap gap-3">
          <button type="button" className={PRIMARY} onClick={() => (hasContent(target) ? setConfirming(true) : copy())}>
            {t("plan.duplicate.copy")}
          </button>
          <button type="button" className={BUTTON} onClick={close}>
            {t("plan.cancel")}
          </button>
        </div>
      )}
    </div>
  );
}

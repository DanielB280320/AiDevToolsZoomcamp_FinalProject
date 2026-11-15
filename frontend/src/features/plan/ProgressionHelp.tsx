import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ChevronDownIcon, LightbulbIcon } from "../../components/icons";
import { CARD, Collapse } from "../../components/card";

const TOPICS = ["range", "increase", "hold", "deload", "effort"] as const;

/** Collapsible explanation of goal-driven progression, with the disclaimer always visible (F11, D107, spec 6.3). */
export function ProgressionHelp() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <section
      aria-labelledby="progression-help-title"
      className={`mt-3 ${CARD}`}
    >
      <h3
        id="progression-help-title"
        className="font-display text-step-1 font-semibold"
      >
        <button
          type="button"
          aria-expanded={open}
          aria-controls="progression-help-content"
          onClick={() => setOpen((was) => !was)}
          className="flex min-h-12 w-full items-center gap-2 text-left hover:text-spruce"
        >
          <LightbulbIcon className="size-6 text-spruce" />
          <span className="min-w-0 flex-1">{t("plan.progression.title")}</span>
          <ChevronDownIcon
            className={`size-6 text-spruce transition-transform ${open ? "rotate-180" : ""}`}
          />
        </button>
      </h3>
      <p className="text-step--1 font-semibold" data-testid="progression-disclaimer">
        {t("plan.progression.disclaimer")}
      </p>
      <Collapse id="progression-help-content" open={open}>
        <p className="text-step--1 text-slate">{t("plan.progression.lead")}</p>
        <ul className="mt-2 flex list-disc flex-col gap-2 pl-5 text-step--1">
          {TOPICS.map(
            (key) => (
              <li key={key}>{t(`plan.progression.${key}`)}</li>
            ),
          )}
        </ul>
      </Collapse>
    </section>
  );
}

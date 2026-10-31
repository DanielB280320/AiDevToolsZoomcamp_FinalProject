import { useState } from "react";
import { useTranslation } from "react-i18next";

import { usePlanVersion, usePlanVersions } from "../../api/plan";
import type { UnitSystem } from "../../lib/units";
import { BUTTON } from "./fields";
import { PlanView } from "./PlanView";

/** Every plan version, newest first (F8.2, F8.3); opening one shows it read-only. */
export function VersionHistory({ athleteId, units, timezone }: { athleteId: string; units: UnitSystem; timezone: string }) {
  const { t, i18n } = useTranslation();
  const [open, setOpen] = useState<number | null>(null);
  const list = usePlanVersions(athleteId);
  const version = usePlanVersion(athleteId, open);
  const date = (iso: string) =>
    new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short", timeZone: timezone }).format(new Date(iso));

  if (open !== null) {
    return (
      <section aria-label={t("plan.history.viewing", { version: open })}>
        <button type="button" className={BUTTON} onClick={() => setOpen(null)}>
          {t("plan.history.back")}
        </button>
        <h3 className="mt-4 font-display text-step-2 font-bold">{t("plan.history.viewing", { version: open })}</h3>
        <p className="mt-1 border-l-4 border-iron pl-3">{t("plan.history.readOnly")}</p>
        {version.isPending && <p role="status">{t("plan.loading")}</p>}
        {version.isError && <p role="alert" className="font-semibold text-alert">{t("plan.history.failed")}</p>}
        {version.data && (
          <div className="mt-4">
            <PlanView plan={version.data} units={units} />
          </div>
        )}
      </section>
    );
  }

  return (
    <section aria-label={t("plan.tabs.history")}>
      {list.isPending && <p role="status">{t("plan.loading")}</p>}
      {list.isError && <p role="alert" className="font-semibold text-alert">{t("plan.history.failed")}</p>}
      <ul className="flex flex-col gap-3">
        {(list.data ?? []).map((v) => (
          <li key={v.id} className="border-2 border-iron/30 p-3">
            <p className="font-display text-step-1 font-bold">
              {t("plan.history.version", { version: v.version })}
              {v.active && <span className="ml-2 text-step--1 font-semibold text-spruce-dark">{t("plan.history.active")}</span>}
            </p>
            <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 text-step--1">
              <dt className="font-semibold">{t("plan.history.date")}</dt>
              <dd>{date(v.created_at)}</dd>
              <dt className="font-semibold">{t("plan.history.source")}</dt>
              <dd>{t(`plan.history.sources.${v.source}`)}</dd>
              <dt className="font-semibold">{t("plan.history.author")}</dt>
              <dd>{v.created_by ? t(`plan.history.roles.${v.created_by.role}`) : t("plan.history.roles.unknown")}</dd>
            </dl>
            <button type="button" className={`${BUTTON} mt-2`} onClick={() => setOpen(v.version)} aria-label={t("plan.history.open", { version: v.version })}>
              {t("plan.history.openButton")}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { type CoachAthleteSummary, useCoachAthletes } from "../../api/coach";
import { DAY_FORMAT, formatDay } from "../../lib/calendarDates";
import { paths } from "../../paths";
import { QueryState } from "../calendar/QueryState";

const COLUMNS = ["client", "adherence", "lastLog", "pending"] as const;
const CELL = "block px-0 py-1 before:block before:text-step--1 before:font-semibold before:text-slate before:content-[attr(data-label)] lg:table-cell lg:px-3 lg:py-3 lg:before:hidden";

function Attention({ client }: { client: CoachAthleteSummary }) {
  const { t } = useTranslation();
  if (!client.needs_attention) return null;
  return (
    <span className="mt-1 flex flex-wrap items-center gap-1">
      <span className="rounded-sm bg-alert px-2 py-0.5 text-step--1 font-bold text-chalk">{t("coach.clients.needsAttention")}</span>
      {client.attention_reasons.map((reason) => (
        <span key={reason} data-testid="attention-reason" className="rounded-sm border border-alert px-2 py-0.5 text-step--1 font-semibold text-alert">
          {t(`coach.clients.reasons.${reason}`)}
        </span>
      ))}
    </span>
  );
}

function Row({ client }: { client: CoachAthleteSummary }) {
  const { t, i18n } = useTranslation();
  const adherence = client.training_adherence_7d;
  return (
    <tr
      data-testid="client-row"
      data-needs-attention={client.needs_attention}
      className="mb-3 block border-2 border-iron/30 p-3 lg:mb-0 lg:table-row lg:border-0 lg:border-b lg:p-0"
    >
      <td className={CELL} data-label={t("coach.clients.columns.client")}>
        <Link
          to={paths.coachClient(client.athlete.id)}
          className="inline-flex min-h-11 items-center break-words font-display text-step-1 font-bold text-spruce underline underline-offset-4"
        >
          {client.athlete.display_name}
        </Link>
        <Attention client={client} />
      </td>
      <td className={CELL} data-label={t("coach.clients.columns.adherence")}>
        {adherence === null ? (
          <span aria-label={t("coach.clients.noAdherenceLabel")}>{t("coach.clients.noAdherence")}</span>
        ) : (
          t("coach.clients.percent", { value: Math.round(adherence * 100) })
        )}
      </td>
      <td className={CELL} data-label={t("coach.clients.columns.lastLog")}>
        {client.last_log_date === null ? t("coach.clients.noLogs") : formatDay(client.last_log_date, i18n.language, DAY_FORMAT.dayMonth)}
      </td>
      <td className={CELL} data-label={t("coach.clients.columns.pending")}>
        {client.pending_suggestion_count}
      </td>
    </tr>
  );
}

/** The coach's clients in the order the API returns them (needs attention first, F16.5). Never re-sorted here. */
export function ClientList() {
  const { t } = useTranslation();
  const clients = useCoachAthletes();
  if (!clients.data) {
    return <QueryState isPending={clients.isPending} isError={clients.isError} onRetry={() => void clients.refetch()} />;
  }
  if (clients.data.length === 0) {
    return (
      <div className="mt-6 max-w-[52ch] border-l-4 border-iron pl-3">
        <p className="font-semibold">{t("coach.clients.emptyTitle")}</p>
        <p className="mt-1">{t("coach.clients.emptyBody")}</p>
        <p className="mt-3">
          <Link to={paths.coach} className="inline-flex min-h-11 items-center font-semibold text-spruce underline underline-offset-4">
            {t("coach.clients.emptyLink")}
          </Link>
        </p>
      </div>
    );
  }
  return (
    <table className="mt-4 block w-full lg:table">
      <caption className="sr-only">{t("coach.clients.caption")}</caption>
      <thead className="hidden lg:table-header-group">
        <tr className="border-b-4 border-iron text-left">
          {COLUMNS.map((key) => (
            <th key={key} scope="col" className="px-3 py-2 font-display text-step-0 font-bold">
              {t(`coach.clients.columns.${key}`)}
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="block lg:table-row-group">
        {clients.data.map((client) => (
          <Row key={client.link_id} client={client} />
        ))}
      </tbody>
    </table>
  );
}

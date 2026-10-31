import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { type CoachLink, useCoachLinkAction, useCoachLinks, useCoachSearch, useRequestCoachLink } from "../../api/coach";
import { QueryState } from "../calendar/QueryState";
import { linkErrorKey } from "./linkErrors";

const MIN_QUERY = 3;
const button = "min-h-12 rounded-md bg-spruce px-4 font-semibold text-chalk hover:bg-spruce-dark aria-disabled:opacity-75";
const outline = "min-h-12 rounded-md border-2 border-iron px-4 font-semibold hover:bg-line aria-disabled:opacity-75";

/** Athlete side of F16 linking: the current coach or pending request, else search and request. */
export function AthleteCoach() {
  const links = useCoachLinks();
  if (!links.data) {
    return <QueryState isPending={links.isPending} isError={links.isError} onRetry={() => void links.refetch()} />;
  }
  const current = links.data.find((l) => l.status === "active") ?? links.data.find((l) => l.status === "pending");
  return current ? <CurrentCoach link={current} /> : <FindCoach />;
}

function CurrentCoach({ link }: { link: CoachLink }) {
  const { t } = useTranslation();
  const act = useCoachLinkAction();
  const pending = link.status === "pending";
  const name = link.coach.display_name;
  return (
    <section aria-labelledby="current-coach-heading" className="mt-6 border-l-4 border-iron pl-4">
      <h2 id="current-coach-heading" className="font-display text-step-2 font-bold">
        {t(pending ? "coach.athlete.pendingTitle" : "coach.athlete.currentTitle")}
      </h2>
      <p className="mt-1 font-semibold">{name}</p>
      <p className="mt-1 text-slate">{t(pending ? "coach.athlete.pendingBody" : "coach.athlete.activeBody", { name })}</p>
      {act.isError && (
        <p role="alert" className="mt-2 font-semibold text-alert">
          {t(`coach.errors.${linkErrorKey(act.error)}`)}
        </p>
      )}
      <button
        type="button"
        aria-disabled={act.isPending || undefined}
        onClick={() => {
          if (!act.isPending) act.mutate({ id: link.id, action: "end" });
        }}
        className={`mt-3 ${outline}`}
      >
        {t("coach.athlete.endLink")}
      </button>
    </section>
  );
}

function FindCoach() {
  const { t } = useTranslation();
  const [text, setText] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [short, setShort] = useState(false);
  const search = useCoachSearch(submitted);
  const request = useRequestCoachLink();

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    const q = text.trim();
    setShort(q.length < MIN_QUERY);
    if (q.length >= MIN_QUERY) setSubmitted(q);
  };

  return (
    <section aria-labelledby="find-coach-heading" className="mt-6">
      <h2 id="find-coach-heading" className="font-display text-step-2 font-bold">
        {t("coach.athlete.searchTitle")}
      </h2>
      <form onSubmit={onSubmit} noValidate className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="flex-1">
          <label htmlFor="coach-search" className="block font-semibold">
            {t("coach.athlete.searchLabel")}
          </label>
          <input
            id="coach-search"
            type="search"
            value={text}
            onChange={(event) => setText(event.target.value)}
            maxLength={254}
            aria-invalid={short || undefined}
            aria-describedby={short ? "coach-search-error" : "coach-search-hint"}
            className="mt-1.5 block min-h-12 w-full rounded-md border-2 border-iron/35 bg-white px-3 py-2 text-iron aria-[invalid=true]:border-alert"
          />
          {short ? (
            <p id="coach-search-error" className="mt-1.5 text-step--1 font-semibold text-alert">
              {t("coach.athlete.tooShort")}
            </p>
          ) : (
            <p id="coach-search-hint" className="mt-1 text-step--1 text-slate">
              {t("coach.athlete.searchHint")}
            </p>
          )}
        </div>
        <button type="submit" className={button}>
          {t("coach.athlete.searchButton")}
        </button>
      </form>

      {request.isError && (
        <p role="alert" className="mt-4 border-l-4 border-alert pl-3 font-semibold text-alert">
          {t(`coach.errors.${linkErrorKey(request.error)}`)}
        </p>
      )}
      {submitted && search.isError && (
        <p role="alert" className="mt-4 font-semibold text-alert">
          {t("coach.loadFailed")}
        </p>
      )}
      {submitted && search.data && search.data.length === 0 && <p className="mt-4 text-slate">{t("coach.athlete.noResults")}</p>}
      {search.data && search.data.length > 0 && (
        <ul aria-label={t("coach.athlete.resultsLabel")} className="mt-4 divide-y divide-line border-y border-line">
          {search.data.map((coach) => (
            <li key={coach.id} className="flex items-start justify-between gap-4 py-3">
              <div>
                <p className="font-semibold">{coach.display_name}</p>
                <p className="text-slate">{coach.bio || t("coach.athlete.noBio")}</p>
              </div>
              <button
                type="button"
                aria-label={t("coach.athlete.requestFor", { name: coach.display_name })}
                aria-disabled={request.isPending || undefined}
                onClick={() => {
                  if (!request.isPending) request.mutate(coach.id);
                }}
                className={`shrink-0 ${button}`}
              >
                {t("coach.athlete.request")}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

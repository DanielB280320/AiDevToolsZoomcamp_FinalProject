import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { type CoachLink, useCoachLinkAction, useCoachLinks, useCoachProfile, useUpdateCoachProfile } from "../../api/coach";
import { QueryState } from "../calendar/QueryState";
import { linkErrorKey } from "./linkErrors";

const BIO_MAX = 500;
const button = "min-h-12 rounded-md bg-spruce px-4 font-semibold text-chalk hover:bg-spruce-dark aria-disabled:opacity-75";
const outline = "min-h-12 rounded-md border-2 border-iron px-4 font-semibold hover:bg-line aria-disabled:opacity-75";

/** Coach side of F16: profile form, incoming requests, linked athletes. */
export function CoachPanel() {
  return (
    <>
      <ProfileForm />
      <Links />
    </>
  );
}

function ProfileForm() {
  const { t } = useTranslation();
  const profile = useCoachProfile();
  if (!profile.data) {
    return <QueryState isPending={profile.isPending} isError={profile.isError} onRetry={() => void profile.refetch()} />;
  }
  return <ProfileFields initial={{ bio: profile.data.bio, discoverable: profile.data.discoverable }} title={t("coach.coach.profileTitle")} />;
}

function ProfileFields({ initial, title }: { initial: { bio: string; discoverable: boolean }; title: string }) {
  const { t } = useTranslation();
  const update = useUpdateCoachProfile();
  const [bio, setBio] = useState(initial.bio);
  const [discoverable, setDiscoverable] = useState(initial.discoverable);

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!update.isPending) update.mutate({ bio, discoverable });
  };
  return (
    <section aria-labelledby="coach-profile-heading" className="mt-6">
      <h2 id="coach-profile-heading" className="font-display text-step-2 font-bold">
        {title}
      </h2>
      <form onSubmit={onSubmit} className="mt-3 flex flex-col gap-4">
        <div>
          <label htmlFor="coach-bio" className="block font-semibold">
            {t("coach.coach.bioLabel")}
          </label>
          <p id="coach-bio-hint" className="mt-1 text-step--1 text-slate">
            {t("coach.coach.bioHint")}
          </p>
          <textarea
            id="coach-bio"
            rows={4}
            value={bio}
            maxLength={BIO_MAX}
            onChange={(event) => setBio(event.target.value)}
            aria-describedby="coach-bio-hint"
            className="mt-1.5 block w-full rounded-md border-2 border-iron/35 bg-white px-3 py-2 text-iron"
          />
        </div>
        <div className="flex items-start gap-3">
          <input
            id="coach-discoverable"
            type="checkbox"
            checked={discoverable}
            onChange={(event) => setDiscoverable(event.target.checked)}
            className="mt-0.5 size-6 shrink-0 cursor-pointer accent-spruce"
          />
          <label htmlFor="coach-discoverable" className="cursor-pointer font-semibold">
            {t("coach.coach.discoverable")}
          </label>
        </div>
        {update.isError && (
          <p role="alert" className="font-semibold text-alert">
            {t("coach.coach.saveFailed")}
          </p>
        )}
        {update.isSuccess && (
          <p role="status" className="border-l-4 border-spruce pl-3 font-semibold">
            {t("coach.coach.saved")}
          </p>
        )}
        <div>
          <button type="submit" aria-disabled={update.isPending || undefined} className={button}>
            {t(update.isPending ? "coach.coach.saving" : "coach.coach.save")}
          </button>
        </div>
      </form>
    </section>
  );
}

function Links() {
  const { t } = useTranslation();
  const links = useCoachLinks();
  const act = useCoachLinkAction();
  if (!links.data) {
    return <QueryState isPending={links.isPending} isError={links.isError} onRetry={() => void links.refetch()} />;
  }
  const incoming = links.data.filter((l) => l.status === "pending");
  const active = links.data.filter((l) => l.status === "active");
  const run = (link: CoachLink, action: "approve" | "decline" | "end") => {
    if (!act.isPending) act.mutate({ id: link.id, action });
  };
  const busy = act.isPending || undefined;
  return (
    <>
      {act.isError && (
        <p role="alert" className="mt-6 border-l-4 border-alert pl-3 font-semibold text-alert">
          {t(`coach.errors.${linkErrorKey(act.error)}`)}
        </p>
      )}
      <section aria-labelledby="incoming-heading" className="mt-8">
        <h2 id="incoming-heading" className="font-display text-step-2 font-bold">
          {t("coach.coach.incomingTitle")}
        </h2>
        {incoming.length === 0 ? (
          <p className="mt-2 text-slate">{t("coach.coach.noIncoming")}</p>
        ) : (
          <ul className="mt-3 divide-y divide-line border-y border-line">
            {incoming.map((link) => (
              <li key={link.id} className="py-3">
                <p>{t("coach.coach.incomingBody", { name: link.athlete.display_name })}</p>
                <div className="mt-2 flex flex-wrap gap-3">
                  <button type="button" aria-disabled={busy} onClick={() => run(link, "approve")} className={button}>
                    {t("coach.coach.approve")}
                  </button>
                  <button type="button" aria-disabled={busy} onClick={() => run(link, "decline")} className={outline}>
                    {t("coach.coach.decline")}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section aria-labelledby="athletes-heading" className="mt-8">
        <h2 id="athletes-heading" className="font-display text-step-2 font-bold">
          {t("coach.coach.athletesTitle")}
        </h2>
        {active.length === 0 ? (
          <p className="mt-2 text-slate">{t("coach.coach.noAthletes")}</p>
        ) : (
          <ul className="mt-3 divide-y divide-line border-y border-line">
            {active.map((link) => (
              <li key={link.id} className="flex items-center justify-between gap-4 py-3">
                <p className="font-semibold">{link.athlete.display_name}</p>
                <button
                  type="button"
                  aria-label={t("coach.coach.endLinkFor", { name: link.athlete.display_name })}
                  aria-disabled={busy}
                  onClick={() => run(link, "end")}
                  className={outline}
                >
                  {t("coach.coach.endLink")}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

import { useTranslation } from "react-i18next";

import { useAthleteProfile, useAthleteTargets } from "../../api/athlete";
import { formatLength, type UnitSystem } from "../../lib/units";
import { QueryState } from "../calendar/QueryState";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap justify-between gap-x-4 border-b border-line py-2">
      <dt className="font-semibold">{label}</dt>
      <dd className="min-w-0 break-words text-right">{children}</dd>
    </div>
  );
}

/** A client's profile and daily targets, read-only (F16, F3). Lengths are shown in the client's units. */
export function ClientProfile({ athleteId, units }: { athleteId: string; units: UnitSystem }) {
  const { t } = useTranslation();
  const profile = useAthleteProfile(athleteId);
  const targets = useAthleteTargets(athleteId);
  return (
    <>
      <section aria-labelledby="client-profile-heading" className="mt-2">
        <h2 id="client-profile-heading" className="font-display text-step-2 font-bold">
          {t("coach.client.profile.title")}
        </h2>
        {!profile.data ? (
          <QueryState isPending={profile.isPending} isError={profile.isError} onRetry={() => void profile.refetch()} />
        ) : (
          <dl className="mt-2">
            <Row label={t("onboarding.review.rows.height")}>{formatLength(profile.data.height_cm, units)}</Row>
            <Row label={t("onboarding.review.rows.goal")}>{t(`onboarding.goal.${profile.data.goal}`)}</Row>
            <Row label={t("onboarding.review.rows.experience")}>{t(`onboarding.training.experience.${profile.data.experience}`)}</Row>
            <Row label={t("onboarding.review.rows.training")}>
              {t("onboarding.review.trainingValue", {
                days: profile.data.days_per_week,
                list: profile.data.preferred_days.map((d) => t(`plan.weekday.${d}`)).join(", "),
                minutes: profile.data.session_minutes,
              })}
            </Row>
            <Row label={t("onboarding.review.rows.meals")}>{profile.data.meals_per_day}</Row>
          </dl>
        )}
      </section>
      <section aria-labelledby="client-targets-heading" className="mt-8 border-t-4 border-iron pt-3">
        <h2 id="client-targets-heading" className="font-display text-step-2 font-bold">
          {t("onboarding.result.targets")}
        </h2>
        {!targets.data ? (
          <QueryState isPending={targets.isPending} isError={targets.isError} onRetry={() => void targets.refetch()} />
        ) : (
          <dl className="mt-2">
            <Row label={t("onboarding.result.kcal")}>{t("onboarding.result.kcalValue", { value: targets.data.kcal })}</Row>
            <Row label={t("onboarding.result.protein")}>{t("onboarding.result.gramsValue", { value: targets.data.protein_g })}</Row>
            <Row label={t("onboarding.result.carbs")}>{t("onboarding.result.gramsValue", { value: targets.data.carbs_g })}</Row>
            <Row label={t("onboarding.result.fat")}>{t("onboarding.result.gramsValue", { value: targets.data.fat_g })}</Row>
          </dl>
        )}
      </section>
    </>
  );
}

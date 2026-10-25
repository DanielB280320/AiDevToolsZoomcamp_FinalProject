import { type FormEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate } from "react-router";

import { isApiError } from "../api/errors";
import { type OnboardingResult, useCompleteOnboarding } from "../api/onboarding";
import { ChoiceField, focusTargetId, FormAlert, SubmitButton } from "../components/form/fields";
import { MultiChoiceField, NumberField } from "../components/form/wizardFields";
import { useFocusAfterRender } from "../components/form/useFocusAfterRender";
import { useSignedInUser } from "../components/RequireAuth";
import { formatHeight, formatWeight, lengthUnit, weightUnit } from "../lib/units";
import type { Schemas } from "../api/client";
import { paths } from "../paths";
import { UNIT_SYMBOLS, wizardChoices } from "../onboarding/choices";
import { ExercisePicker } from "../onboarding/ExercisePicker";
import {
  buildRequest,
  DAYS_PER_WEEK,
  emptyValues,
  type FieldErrors,
  heightToCm,
  MEALS_PER_DAY,
  needsHip,
  SESSION_MINUTES,
  STEPS,
  type StepId,
  stepOfField,
  validateStep,
  WEEKDAYS,
  type WizardValues,
  weightToKg,
} from "../onboarding/model";

type Weekday = Schemas["Weekday"];
type Allergen = Schemas["Allergen"];

const FORM_ALERT_ID = "onboarding-error";

export function OnboardingPage() {
  const { t } = useTranslation();
  const me = useSignedInUser();
  const units = me.units;
  const focus = useFocusAfterRender();
  const submit = useCompleteOnboarding(me.id);

  const [values, setValues] = useState<WizardValues>(emptyValues);
  const [stepIndex, setStepIndex] = useState(0); // STEPS.length = review
  const [errors, setErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | undefined>();
  const [result, setResult] = useState<OnboardingResult | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const moved = useRef(false);

  // Move focus to the step heading when the step changes, so screen readers announce it.
  useEffect(() => {
    if (moved.current) headingRef.current?.focus();
    moved.current = true;
  }, [stepIndex, result]);

  // Athletes who already finished onboarding have nothing to do here (unless showing their result).
  if (me.role !== "athlete" || (me.onboarding_completed && !result)) {
    return <Navigate to={paths.today} replace />;
  }

  if (result) return <ResultStep result={result} headingRef={headingRef} />;

  const set = <K extends keyof WizardValues>(field: K) => (value: WizardValues[K]) => {
    setValues((previous) => ({ ...previous, [field]: value }));
    setErrors((previous) => (field in previous ? Object.fromEntries(Object.entries(previous).filter(([key]) => key !== field)) : previous));
  };

  const onReview = stepIndex === STEPS.length;
  const step: StepId | "review" = onReview ? "review" : STEPS[stepIndex]!;
  const e = errors;

  const focusError = (found: FieldErrors) => {
    const order = ["sex", "height", "weight", "bodyFatMethod", "bodyFat", "neck", "waist", "hip", "lifestyle", "goal", "experience", "daysPerWeek", "preferredDays", "sessionMinutes", "equipment", "diet", "mealsPerDay"];
    const field = order.find((key) => found[key]);
    if (!field) return;
    const radio: Record<string, string> = {
      sex: "male",
      bodyFatMethod: "entered",
      lifestyle: "sedentary",
      goal: "recomposition",
      experience: "beginner",
      daysPerWeek: String(DAYS_PER_WEEK[0]),
      sessionMinutes: String(SESSION_MINUTES[0]),
      equipment: "full_gym",
      diet: "omnivore",
      mealsPerDay: String(MEALS_PER_DAY[0]),
      preferredDays: WEEKDAYS[0]!,
    };
    focus(focusTargetId(field === "height" && units === "imperial" ? "height" : field, radio[field]));
  };

  const next = () => {
    if (onReview) return;
    const found = validateStep(step as StepId, values, units, t);
    if (Object.keys(found).length > 0) {
      setErrors(found);
      focusError(found);
      return;
    }
    setErrors({});
    setStepIndex(stepIndex + 1);
  };

  const create = async () => {
    if (submit.isPending) return;
    setFormError(undefined);
    // Every step is re-validated: the review step is reachable only after them, but a refactor must not skip one.
    for (let i = 0; i < STEPS.length; i += 1) {
      const found = validateStep(STEPS[i]!, values, units, t);
      if (Object.keys(found).length > 0) {
        setErrors(found);
        setStepIndex(i);
        focusError(found);
        return;
      }
    }
    try {
      setResult(await submit.mutateAsync(buildRequest(values, units)));
    } catch (error) {
      if (isApiError(error) && error.problem.code === "already_onboarded") {
        setFormError(t("onboarding.errors.alreadyOnboarded"));
      } else if (isApiError(error) && error.problem.code === "validation_error") {
        const bad = Object.keys(error.problem.fieldErrors)
          .map((key) => stepOfField(key.split(/[./]/).pop() ?? key))
          .find(Boolean);
        if (bad) setStepIndex(STEPS.indexOf(bad));
        setFormError(t("onboarding.errors.invalidRequest"));
      } else if (isApiError(error) && error.status < 500) {
        setFormError(t("onboarding.errors.invalidRequest"));
      } else {
        setFormError(isApiError(error) ? t("errors.unexpected") : t("errors.network"));
      }
      focus(FORM_ALERT_ID);
    }
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (onReview) void create();
    else next();
  };

  const toggle = <T,>(list: T[], item: T): T[] => (list.includes(item) ? list.filter((x) => x !== item) : [...list, item]);
  const c = wizardChoices(t);
  const u = UNIT_SYMBOLS;
  const num = (field: "daysPerWeek" | "sessionMinutes" | "mealsPerDay") => (v: string) => set(field)(Number(v));
  const on = {
    sex: set("sex"),
    height: set("height"),
    heightInches: set("heightInches"),
    weight: set("weight"),
    bodyFatMethod: set("bodyFatMethod"),
    bodyFat: set("bodyFat"),
    neck: set("neck"),
    waist: set("waist"),
    hip: set("hip"),
    lifestyle: set("lifestyle"),
    goal: set("goal"),
    experience: set("experience"),
    equipment: set("equipment"),
    diet: set("diet"),
    avoidedExercises: set("avoidedExercises"),
    daysPerWeek: num("daysPerWeek"),
    sessionMinutes: num("sessionMinutes"),
    mealsPerDay: num("mealsPerDay"),
    toggleDay: (day: Weekday) => set("preferredDays")(toggle(values.preferredDays, day)),
    toggleAllergy: (a: Allergen) => set("allergies")(toggle(values.allergies, a)),
  };
  const lu = lengthUnit(units);
  const wu = weightUnit(units);

  const stepName = t(`onboarding.stepNames.${step}`);
  const total = STEPS.length + 1;

  return (
    <article className="max-w-[40rem]">
      <p className="text-step-0 font-semibold text-slate">{t("onboarding.title")}</p>
      <div
        role="progressbar"
        aria-valuemin={1}
        aria-valuemax={total}
        aria-valuenow={stepIndex + 1}
        aria-label={t("onboarding.progress", { current: stepIndex + 1, total, name: stepName })}
        className="mt-2 flex gap-1"
      >
        {Array.from({ length: total }, (_, i) => (
          <span key={i} className={"h-2 flex-1 rounded-sm " + (i <= stepIndex ? "bg-spruce" : "bg-line")} />
        ))}
      </div>
      <p className="mt-2 text-step--1 text-slate">{t("onboarding.progress", { current: stepIndex + 1, total, name: stepName })}</p>

      <form noValidate onSubmit={onSubmit} aria-label={stepName} className="mt-6 flex flex-col gap-6">
        <h1 ref={headingRef} tabIndex={-1} className="font-display text-step-4 font-bold focus:outline-none">
          {t(`onboarding.${step}.title`)}
        </h1>
        <p className="-mt-3 max-w-[52ch]">{t(`onboarding.${step}.lead`)}</p>
        {formError && <FormAlert id={FORM_ALERT_ID}>{formError}</FormAlert>}

        {step === "body" && (
          <>
            <ChoiceField
              id="sex"
              legend={t("onboarding.body.sex.legend")}
              hint={t("onboarding.body.sex.hint")}
              value={values.sex}
              onChange={on.sex}
              choices={c.sex}
              error={e.sex}
            />
            {units === "metric" ? (
              <NumberField id="height" label={t("onboarding.body.height.label")} unit={u.cm} value={values.height} onChange={on.height} error={e.height} />
            ) : (
              <div className="grid grid-cols-2 gap-4">
                <NumberField id="height" label={t("onboarding.body.height.feet")} unit={u.ft} value={values.height} onChange={on.height} error={e.height} />
                <NumberField id="heightInches" label={t("onboarding.body.height.inches")} unit={u.in} value={values.heightInches} onChange={on.heightInches} />
              </div>
            )}
            <NumberField id="weight" label={t("onboarding.body.weight.label")} unit={wu} value={values.weight} onChange={on.weight} error={e.weight} />
          </>
        )}

        {step === "bodyFat" && (
          <>
            <ChoiceField
              id="bodyFatMethod"
              legend={t("onboarding.bodyFat.method.legend")}
              value={values.bodyFatMethod}
              onChange={on.bodyFatMethod}
              choices={c.bodyFatMethod}
              error={e.bodyFatMethod}
            />
            {values.bodyFatMethod === "entered" && (
              <NumberField id="bodyFat" label={t("onboarding.bodyFat.percent.label")} unit={u.percent} hint={t("onboarding.bodyFat.percent.hint")} value={values.bodyFat} onChange={on.bodyFat} error={e.bodyFat} />
            )}
            {values.bodyFatMethod === "navy" && (
              <>
                <p className="max-w-[52ch] text-step--1 text-slate">{t("onboarding.bodyFat.navyHint")}</p>
                <NumberField id="neck" label={t("onboarding.bodyFat.neck.label")} unit={lu} value={values.neck} onChange={on.neck} error={e.neck} />
                <NumberField id="waist" label={t("onboarding.bodyFat.waist.label")} unit={lu} hint={t("onboarding.bodyFat.waist.hint")} value={values.waist} onChange={on.waist} error={e.waist} />
                {needsHip(values.sex) && (
                  <NumberField id="hip" label={t("onboarding.bodyFat.hip.label")} unit={lu} hint={t("onboarding.bodyFat.hip.hint")} value={values.hip} onChange={on.hip} error={e.hip} />
                )}
              </>
            )}
          </>
        )}

        {step === "lifestyle" && (
          <ChoiceField
            id="lifestyle"
            legend={t("onboarding.lifestyle.legend")}
            value={values.lifestyle}
            onChange={on.lifestyle}
            choices={c.lifestyle}
            error={e.lifestyle}
          />
        )}

        {step === "goal" && (
          <ChoiceField
            id="goal"
            legend={t("onboarding.goal.legend")}
            value={values.goal}
            onChange={on.goal}
            choices={c.goal}
            error={e.goal}
          />
        )}

        {step === "training" && (
          <>
            <ChoiceField
              id="experience"
              legend={t("onboarding.training.experience.legend")}
              value={values.experience}
              onChange={on.experience}
              choices={c.experience}
              error={e.experience}
            />
            <ChoiceField
              id="daysPerWeek"
              legend={t("onboarding.training.daysPerWeek.legend")}
              value={values.daysPerWeek === null ? "" : String(values.daysPerWeek)}
              onChange={on.daysPerWeek}
              choices={c.daysPerWeek}
              error={e.daysPerWeek}
            />
            <MultiChoiceField
              id="preferredDays"
              legend={t("onboarding.training.preferredDays.legend")}
              hint={t("onboarding.training.preferredDays.hint")}
              values={values.preferredDays}
              onToggle={on.toggleDay}
              options={c.weekdays}
              error={e.preferredDays}
            />
            <ChoiceField
              id="sessionMinutes"
              legend={t("onboarding.training.sessionMinutes.legend")}
              value={values.sessionMinutes === null ? "" : String(values.sessionMinutes)}
              onChange={on.sessionMinutes}
              choices={c.sessionMinutes}
              error={e.sessionMinutes}
            />
            <ChoiceField
              id="equipment"
              legend={t("onboarding.training.equipment.legend")}
              value={values.equipment}
              onChange={on.equipment}
              choices={c.equipment}
              error={e.equipment}
            />
            <ExercisePicker selected={values.avoidedExercises} onChange={on.avoidedExercises} />
          </>
        )}

        {step === "diet" && (
          <>
            <ChoiceField
              id="diet"
              legend={t("onboarding.diet.diet.legend")}
              value={values.diet}
              onChange={on.diet}
              choices={c.diet}
              error={e.diet}
            />
            <MultiChoiceField
              id="allergies"
              legend={t("onboarding.diet.allergies.legend")}
              hint={t("onboarding.diet.allergies.hint")}
              values={values.allergies}
              onToggle={on.toggleAllergy}
              options={c.allergies}
            />
            <ChoiceField
              id="mealsPerDay"
              legend={t("onboarding.diet.mealsPerDay.legend")}
              value={values.mealsPerDay === null ? "" : String(values.mealsPerDay)}
              onChange={on.mealsPerDay}
              choices={c.mealsPerDay}
              error={e.mealsPerDay}
            />
          </>
        )}

        {step === "review" && <Review values={values} units={units} onEdit={(i) => setStepIndex(i)} />}

        <div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center">
          {stepIndex > 0 && (
            <button
              type="button"
              onClick={() => {
                setErrors({});
                setStepIndex(stepIndex - 1);
              }}
              className="min-h-12 rounded-md border-2 border-iron px-6 py-3 font-semibold hover:bg-white"
            >
              {t("onboarding.nav.back")}
            </button>
          )}
          {onReview ? (
            <SubmitButton pending={submit.isPending}>
              {submit.isPending ? t("onboarding.nav.creating") : t("onboarding.nav.create")}
            </SubmitButton>
          ) : (
            <SubmitButton pending={false}>{t("onboarding.nav.next")}</SubmitButton>
          )}
        </div>
      </form>
    </article>
  );
}

function Review({ values, units, onEdit }: { values: WizardValues; units: "metric" | "imperial"; onEdit: (stepIndex: number) => void }) {
  const { t } = useTranslation();
  const none = t("onboarding.review.none");
  const bodyFat =
    values.bodyFatMethod === "entered"
      ? t("onboarding.review.bodyFatValue.entered", { value: values.bodyFat.trim() })
      : values.bodyFatMethod === "navy"
        ? t("onboarding.review.bodyFatValue.navy")
        : t("onboarding.review.bodyFatValue.skip");
  const cm = heightToCm(values, units);
  const kg = weightToKg(values.weight, units);
  const days = WEEKDAYS.filter((d) => values.preferredDays.includes(d)).map((d) => t(`onboarding.training.weekday.${d}`));

  const sections: { step: StepId; rows: [string, string][] }[] = [
    {
      step: "body",
      rows: [
        [t("onboarding.review.rows.sex"), t(`onboarding.body.sex.${values.sex as "male"}`)],
        [t("onboarding.review.rows.height"), cm === null ? "" : formatHeight(cm, units)],
        [t("onboarding.review.rows.weight"), kg === null ? "" : formatWeight(kg, units)],
      ],
    },
    {
      step: "bodyFat",
      rows: [[t("onboarding.review.rows.bodyFat"), bodyFat]],
    },
    { step: "lifestyle", rows: [[t("onboarding.review.rows.lifestyle"), t(`onboarding.lifestyle.${values.lifestyle as "active"}`)]] },
    { step: "goal", rows: [[t("onboarding.review.rows.goal"), t(`onboarding.goal.${values.goal as "cutting"}`)]] },
    {
      step: "training",
      rows: [
        [t("onboarding.review.rows.experience"), t(`onboarding.training.experience.${values.experience as "beginner"}`)],
        [
          t("onboarding.review.rows.training"),
          t("onboarding.review.trainingValue", { days: values.daysPerWeek, list: days.join(", "), minutes: values.sessionMinutes }),
        ],
        [t("onboarding.review.rows.equipment"), t(`onboarding.training.equipment.${values.equipment as "full_gym"}`)],
        [t("onboarding.review.rows.avoid"), values.avoidedExercises.map((x) => x.name).join(", ") || none],
      ],
    },
    {
      step: "diet",
      rows: [
        [t("onboarding.review.rows.diet"), t(`onboarding.diet.diet.${values.diet as "vegan"}`)],
        [t("onboarding.review.rows.allergies"), values.allergies.map((a) => t(`onboarding.diet.allergies.${a}`)).join(", ") || none],
        [t("onboarding.review.rows.meals"), String(values.mealsPerDay)],
      ],
    },
  ];

  return (
    <div className="flex flex-col gap-5">
      {sections.map(({ step, rows }) => (
        <section key={step} aria-label={t(`onboarding.stepNames.${step}`)} className="border-t-4 border-iron pt-3">
          <div className="flex items-baseline justify-between gap-4">
            <h2 className="font-display text-step-1 font-bold">{t(`onboarding.stepNames.${step}`)}</h2>
            <button
              type="button"
              onClick={() => onEdit(STEPS.indexOf(step))}
              className="min-h-12 font-semibold text-spruce underline"
              aria-label={t("onboarding.review.edit", { section: t(`onboarding.stepNames.${step}`) })}
            >
              {t("onboarding.review.editButton")}
            </button>
          </div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1">
            {rows.map(([label, value]) => (
              <div key={label} className="contents">
                <dt className="text-slate">{label}</dt>
                <dd className="font-semibold">{value}</dd>
              </div>
            ))}
          </dl>
        </section>
      ))}
    </div>
  );
}

function ResultStep({ result, headingRef }: { result: OnboardingResult; headingRef: React.RefObject<HTMLHeadingElement | null> }) {
  const { t } = useTranslation();
  const { targets, plan } = result;
  const figures: [string, string][] = [
    [t("onboarding.result.kcal"), t("onboarding.result.kcalValue", { value: targets.kcal })],
    [t("onboarding.result.protein"), t("onboarding.result.gramsValue", { value: targets.protein_g })],
    [t("onboarding.result.carbs"), t("onboarding.result.gramsValue", { value: targets.carbs_g })],
    [t("onboarding.result.fat"), t("onboarding.result.gramsValue", { value: targets.fat_g })],
  ];

  return (
    <article className="max-w-[40rem]">
      <h1 ref={headingRef} tabIndex={-1} className="font-display text-step-4 font-bold focus:outline-none">
        {t("onboarding.result.title")}
      </h1>
      <p className="mt-2 max-w-[52ch]">{t("onboarding.result.lead")}</p>

      <section aria-labelledby="result-targets" className="mt-6 border-t-4 border-iron pt-3">
        <h2 id="result-targets" className="font-display text-step-1 font-bold">
          {t("onboarding.result.targets")}
        </h2>
        <dl className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {figures.map(([label, value]) => (
            <div key={label}>
              <dt className="text-step--1 text-slate">{label}</dt>
              <dd className="font-display text-step-2 font-bold">{value}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section aria-labelledby="result-explanation" className="mt-6">
        <h2 id="result-explanation" className="font-display text-step-1 font-bold">
          {t("onboarding.result.explanation")}
        </h2>
        <p className="mt-2 max-w-[60ch] whitespace-pre-line">{targets.explanation}</p>
      </section>

      <section aria-labelledby="result-plan" className="mt-6">
        <h2 id="result-plan" className="font-display text-step-1 font-bold">
          {t("onboarding.result.plan")}
        </h2>
        <p className="mt-2">{t("onboarding.result.planSummary", { count: plan.training_days.length })}</p>
        {plan.warnings.length > 0 && (
          <ul aria-label={t("onboarding.result.warnings")} className="mt-2 list-disc pl-5">
            {plan.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        )}
      </section>

      <Link
        to={paths.today}
        className="mt-8 inline-flex min-h-12 items-center rounded-md bg-spruce px-6 py-3 font-semibold text-chalk hover:bg-spruce-dark"
      >
        {t("onboarding.nav.goToToday")}
      </Link>
    </article>
  );
}

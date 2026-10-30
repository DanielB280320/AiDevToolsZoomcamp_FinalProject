import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { isApiError } from "../../api/errors";
import { useLogBodyMetric, type WeighInOutcome } from "../../api/body";
import { NumberField } from "../../components/form/wizardFields";
import { TextField } from "../../components/form/fields";
import { lengthUnit, type UnitSystem, weightUnit } from "../../lib/units";
import { buildWeighIn, formFieldOf, type WeighInErrors, type WeighInField, type WeighInValues } from "./weighIn";

const EMPTY = { weight: "", bodyFat: "", neck: "", waist: "", hip: "" };
const ID = (field: WeighInField) => `weigh-in-${field}`;

/** Weigh-in form (F14): values in the user's units in, metric to the API. */
export function WeighInForm({
  athleteId,
  units,
  today,
  onLogged,
}: {
  athleteId: string;
  units: UnitSystem;
  /** The user's calendar day, `YYYY-MM-DD`. */
  today: string;
  onLogged: (outcome: WeighInOutcome) => void;
}) {
  const { t } = useTranslation();
  const log = useLogBodyMetric(athleteId);
  const [values, setValues] = useState<WeighInValues>({ date: today, ...EMPTY });
  const [errors, setErrors] = useState<WeighInErrors>({});

  const set = (field: WeighInField) => (value: string) => setValues((v) => ({ ...v, [field]: value }));
  const message = (field: WeighInField) => {
    const e = errors[field];
    return !e ? undefined : "key" in e ? t(`body.errors.${e.key}` as "body.errors.generic") : e.message;
  };
  const formError = errors.form;

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (log.isPending) return;
    const built = buildWeighIn(values, units, today);
    if ("errors" in built) {
      setErrors(built.errors);
      const first = (["date", "weight", "bodyFat", "neck", "waist", "hip"] as const).find((f) => built.errors[f]);
      if (first) document.getElementById(ID(first))?.focus();
      return;
    }
    setErrors({});
    try {
      const outcome = await log.mutateAsync(built.input);
      setValues((v) => ({ ...v, ...EMPTY }));
      onLogged(outcome);
    } catch (error) {
      const found: WeighInErrors = {};
      if (isApiError(error) && error.status === 422) {
        for (const [field, text] of Object.entries(error.problem.fieldErrors)) {
          const target = formFieldOf(field);
          if (target && !found[target]) found[target] = { message: text };
        }
        if (Object.keys(found).length === 0) found.form = { key: "form" };
      } else if (isApiError(error) && error.problem.code === "not_onboarded") {
        found.form = { key: "notOnboarded" };
      } else {
        found.form = { key: "generic" };
      }
      setErrors(found);
    }
  };

  const bind = (field: WeighInField) => ({ id: ID(field), value: values[field], onChange: set(field), error: message(field) });
  const date = bind("date");
  const weight = bind("weight");
  const bodyFat = bind("bodyFat");
  const neck = bind("neck");
  const waist = bind("waist");
  const hip = bind("hip");
  const w = weightUnit(units);
  const l = lengthUnit(units);
  return (
    <form onSubmit={(e) => void onSubmit(e)} noValidate className="mt-4 grid max-w-[28rem] gap-4">
      {formError && (
        <p role="alert" className="border-l-4 border-alert pl-3 text-alert">
          {"key" in formError ? t(`body.errors.${formError.key}` as "body.errors.generic") : formError.message}
        </p>
      )}
      <TextField label={t("body.date")} type="date" {...date} max={today} />
      <NumberField label={t("body.weight")} unit={w} {...weight} />
      <NumberField label={t("body.bodyFat")} unit="%" hint={t("body.bodyFatHint")} {...bodyFat} />
      <NumberField label={t("body.neck")} unit={l} {...neck} />
      <NumberField label={t("body.waist")} unit={l} {...waist} />
      <NumberField label={t("body.hip")} unit={l} {...hip} />
      <button
        type="submit"
        aria-disabled={log.isPending || undefined}
        className="min-h-12 rounded-md bg-spruce px-5 font-semibold text-chalk hover:bg-spruce-dark"
      >
        {log.isPending ? t("body.saving") : t("body.save")}
      </button>
    </form>
  );
}

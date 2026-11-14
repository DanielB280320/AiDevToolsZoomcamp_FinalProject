import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { isApiError } from "../../api/errors";
import {
  type CreatePlanRequest,
  type Plan,
  useCreatePlan,
} from "../../api/plan";
import { PlusCircleIcon } from "../../components/icons";
import { localDay } from "../../lib/today";
import { BUTTON, DateInput, PRIMARY, SelectInput, TextInput } from "./fields";

type Scope = NonNullable<CreatePlanRequest["scope"]>;
type StartFrom = NonNullable<CreatePlanRequest["start_from"]>;
type LocalError = "nameRequired" | "nameTooLong" | "startRequired" | "future";
const NAME = "name";
const START = "start_date";
const FROM = ["empty", "generated"] as const;
const SCOPES: Scope[] = ["all", "training", "meals"];
const SCOPE_LABEL = { all: "plan.newPlan.scopeAll", training: "plan.newPlan.scopeTraining", meals: "plan.newPlan.scopeMeals" } as const;
const MAX_NAME = 60;

/** "New plan" (F8, D105): name, start date and what to start from; replaces the current plan from today. */
export function NewPlanForm({
  athleteId,
  timezone,
  unsaved,
  onCreated,
}: {
  athleteId: string;
  timezone: string;
  unsaved: boolean;
  onCreated: (plan: Plan) => void;
}) {
  const { t, i18n } = useTranslation();
  const today = localDay(new Date(), timezone, i18n.language).isoDate;
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [start, setStart] = useState(today);
  const [from, setFrom] = useState<StartFrom>("empty");
  const [scope, setScope] = useState<Scope>("all");
  const [local, setLocal] = useState<Partial<Record<string, LocalError>>>({});
  const [server, setServer] = useState<Record<string, string>>({});
  const create = useCreatePlan(athleteId);

  const error = (field: string): string | undefined => {
    const key = local[field];
    return key ? t(`plan.newPlan.errors.${key}`) : server[field];
  };
  const close = () => {
    setOpen(false);
    setLocal({});
    setServer({});
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    const errors: Partial<Record<string, LocalError>> = {};
    if (trimmed === "") errors.name = "nameRequired";
    else if (trimmed.length > MAX_NAME) errors.name = "nameTooLong";
    if (start === "") errors.start_date = "startRequired";
    else if (start > today) errors.start_date = "future";
    setLocal(errors);
    setServer({});
    if (Object.keys(errors).length > 0) return;
    const body: CreatePlanRequest = {
      name: trimmed,
      start_date: start,
      start_from: from,
      scope: from === "generated" ? scope : "all",
    };
    create.mutate(body, {
      onSuccess: (plan) => {
        setName("");
        setStart(today);
        setFrom("empty");
        setScope("all");
        close();
        onCreated(plan);
      },
      onError: (failure) => {
        if (
          isApiError(failure) &&
          failure.problem.code !== "not_onboarded" &&
          Object.keys(failure.problem.fieldErrors).length > 0
        )
          setServer(failure.problem.fieldErrors);
      },
    });
  };

  const failure = create.error;
  const generic =
    create.isError &&
    !(
      isApiError(failure) && Object.keys(failure.problem.fieldErrors).length > 0
    );

  return (
    <section
      aria-labelledby="plan-new-title"
      className="mt-8 border-t-4 border-iron pt-4"
    >
      <h2
        id="plan-new-title"
        className="flex items-center gap-2 font-display text-step-2 font-bold"
      >
        <PlusCircleIcon className="size-6 text-spruce" />
        {t("plan.newPlan.title")}
      </h2>
      <p className="mt-1 max-w-[52ch]">{t("plan.newPlan.lead")}</p>
      {!open && (
        <button
          type="button"
          className={`${BUTTON} mt-3`}
          aria-expanded={false}
          aria-controls="plan-new-form"
          onClick={() => setOpen(true)}
        >
          {t("plan.newPlan.button")}
        </button>
      )}
      {open && (
        <form
          id="plan-new-form"
          onSubmit={submit}
          noValidate
          aria-labelledby="plan-new-title"
          className="mt-3 flex flex-col gap-4 border-2 border-iron p-3"
        >
          <TextInput
            id="new-plan-name"
            label={t("plan.newPlan.name")}
            value={name}
            maxLength={MAX_NAME + 20}
            onChange={setName}
            hint={t("plan.newPlan.nameHint")}
            error={error(NAME)}
          />
          <DateInput
            id="new-plan-start"
            label={t("plan.newPlan.startDate")}
            value={start}
            max={today}
            onChange={setStart}
            hint={t("plan.newPlan.startDateHint")}
            error={error(START)}
          />
          <fieldset>
            <legend className="font-semibold">
              {t("plan.newPlan.startFrom")}
            </legend>
            {FROM.map((value) => (
              <label
                key={value}
                className="flex min-h-12 items-start gap-3 py-1"
              >
                <input
                  type="radio"
                  name="new-plan-from"
                  value={value}
                  checked={from === value}
                  onChange={() => setFrom(value)}
                  className="mt-1 size-6"
                />
                <span>
                  {value === "empty"
                    ? t("plan.newPlan.startFromEmpty")
                    : t("plan.newPlan.startFromGenerated")}
                  <span className="block text-step--1 text-slate">
                    {value === "empty"
                      ? t("plan.newPlan.startFromEmptyHint")
                      : t("plan.newPlan.startFromGeneratedHint")}
                  </span>
                </span>
              </label>
            ))}
          </fieldset>
          {from === "generated" && (
            <SelectInput
              id="new-plan-scope"
              label={t("plan.newPlan.scope")}
              value={scope}
              onChange={(value) => setScope(value as Scope)}
              options={SCOPES.map((value) => ({ value, label: t(SCOPE_LABEL[value]) }))}
              hint={t("plan.newPlan.scopeHint")}
            />
          )}
          <p className="border-l-4 border-iron pl-3">
            {t("plan.newPlan.replaces")}
          </p>
          {unsaved && (
            <p className="font-semibold">{t("plan.newPlan.unsaved")}</p>
          )}
          <div className="flex flex-wrap gap-3">
            <button
              type="submit"
              className={PRIMARY}
              disabled={create.isPending}
            >
              {create.isPending
                ? t("plan.newPlan.creating")
                : t("plan.newPlan.submit")}
            </button>
            <button type="button" className={BUTTON} onClick={close}>
              {t("plan.cancel")}
            </button>
          </div>
          {generic && (
            <p role="alert" className="font-semibold text-alert">
              {t("plan.newPlan.failed")}
            </p>
          )}
        </form>
      )}
    </section>
  );
}

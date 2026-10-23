import { type FormEvent, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import type { SignUpRequest } from "../api/session";
import { signUp, useStartSession } from "../api/session";
import {
  DISPLAY_NAME_MAX_LENGTH,
  EMAIL_MAX_LENGTH,
  type FormErrors,
  firstErrorField,
  PASSWORD_MAX_LENGTH,
  problemToFormErrors,
  SIGN_UP_FIELDS,
  type SignUpField,
  type SignUpValues,
  validateSignUp,
} from "../auth/forms";
import { AuthLayout } from "../components/AuthLayout";
import {
  CheckboxField,
  type Choice,
  ChoiceField,
  focusTargetId,
  FormAlert,
  SelectField,
  SubmitButton,
  TextField,
} from "../components/form/fields";
import { useFocusAfterRender } from "../components/form/useFocusAfterRender";
import { browserTimeZone, timeZoneOptions } from "../lib/timezones";
import { paths } from "../paths";

const FORM_ALERT_ID = "sign-up-error";
const DISCLAIMER_TEXT_ID = "sign-up-disclaimer";

export function SignUpPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const focus = useFocusAfterRender();
  const session = useStartSession(signUp);

  const [values, setValues] = useState<SignUpValues>(() => ({
    email: "",
    password: "",
    display_name: "",
    role: "",
    birth_date: "",
    units: "metric",
    timezone: browserTimeZone(),
    accept_disclaimer: false,
  }));
  const [errors, setErrors] = useState<FormErrors<SignUpField>>({ fields: {} });
  const zones = useMemo(() => timeZoneOptions(values.timezone), [values.timezone]);

  const set = <K extends keyof SignUpValues>(field: K) => (value: SignUpValues[K]) =>
    setValues((previous) => ({ ...previous, [field]: value }));
  const change = {
    email: set("email"),
    password: set("password"),
    display_name: set("display_name"),
    role: set("role"),
    birth_date: set("birth_date"),
    units: set("units"),
    timezone: set("timezone"),
    accept_disclaimer: set("accept_disclaimer"),
  };

  const roles: Choice<SignUpRequest["role"]>[] = [
    { value: "athlete", label: t("auth.fields.role.athlete"), detail: t("auth.fields.role.athleteDetail") },
    { value: "coach", label: t("auth.fields.role.coach"), detail: t("auth.fields.role.coachDetail") },
  ];
  const units: Choice<SignUpRequest["units"]>[] = [
    { value: "metric", label: t("auth.fields.units.metric"), detail: t("auth.fields.units.metricDetail") },
    { value: "imperial", label: t("auth.fields.units.imperial"), detail: t("auth.fields.units.imperialDetail") },
  ];

  const showErrors = (next: FormErrors<SignUpField>) => {
    setErrors(next);
    const field = firstErrorField(SIGN_UP_FIELDS, next.fields);
    if (field === "role") focus(focusTargetId("role", roles[0]!.value));
    else if (field === "units") focus(focusTargetId("units", units[0]!.value));
    else focus(field ?? FORM_ALERT_ID);
  };

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (session.isPending) return;

    const fieldErrors = validateSignUp(values, t);
    if (Object.keys(fieldErrors).length > 0) {
      showErrors({ fields: fieldErrors });
      return;
    }
    setErrors({ fields: {} });

    try {
      await session.mutateAsync({
        email: values.email.trim(),
        password: values.password,
        display_name: values.display_name.trim(),
        role: values.role as SignUpRequest["role"],
        birth_date: values.birth_date,
        units: values.units as SignUpRequest["units"],
        timezone: values.timezone,
        accept_disclaimer: values.accept_disclaimer,
      });
      navigate(paths.today, { replace: true });
    } catch (error) {
      showErrors(problemToFormErrors(error, SIGN_UP_FIELDS, t));
    }
  };

  const e = errors.fields;
  return (
    <AuthLayout
      title={t("auth.signUp.title")}
      lead={t("auth.signUp.lead")}
      switchPrompt={t("auth.signUp.switchPrompt")}
      switchLink={t("auth.signUp.switchLink")}
      switchTo={paths.signIn}
    >
      <form noValidate onSubmit={onSubmit} aria-label={t("auth.signUp.title")} className="flex flex-col gap-6">
        {errors.form && <FormAlert id={FORM_ALERT_ID}>{errors.form}</FormAlert>}

        <TextField
          id="email"
          type="email"
          label={t("auth.fields.email.label")}
          value={values.email}
          onChange={change.email}
          autoComplete="email"
          maxLength={EMAIL_MAX_LENGTH}
          error={e.email}
        />
        <TextField
          id="password"
          type="password"
          label={t("auth.fields.password.label")}
          hint={t("auth.fields.password.newHint")}
          value={values.password}
          onChange={change.password}
          autoComplete="new-password"
          maxLength={PASSWORD_MAX_LENGTH}
          error={e.password}
        />
        <TextField
          id="display_name"
          label={t("auth.fields.displayName.label")}
          hint={t("auth.fields.displayName.hint")}
          value={values.display_name}
          onChange={change.display_name}
          autoComplete="nickname"
          maxLength={DISPLAY_NAME_MAX_LENGTH}
          error={e.display_name}
        />
        <ChoiceField
          id="role"
          legend={t("auth.fields.role.legend")}
          hint={t("auth.fields.role.hint")}
          value={values.role}
          onChange={change.role}
          choices={roles}
          error={e.role}
        />
        <TextField
          id="birth_date"
          type="date"
          label={t("auth.fields.birthDate.label")}
          hint={t("auth.fields.birthDate.hint")}
          value={values.birth_date}
          onChange={change.birth_date}
          autoComplete="bday"
          error={e.birth_date}
        />
        <ChoiceField
          id="units"
          legend={t("auth.fields.units.legend")}
          hint={t("auth.fields.units.hint")}
          value={values.units}
          onChange={change.units}
          choices={units}
          error={e.units}
        />
        <SelectField
          id="timezone"
          label={t("auth.fields.timezone.label")}
          hint={t("auth.fields.timezone.hint")}
          value={values.timezone}
          onChange={change.timezone}
          options={zones}
          error={e.timezone}
        />

        <div className="border-l-4 border-iron bg-white px-4 py-4">
          <p id={DISCLAIMER_TEXT_ID} className="max-w-[60ch] text-step--1">
            {t("footer.disclaimer")}
          </p>
          <div className="mt-4">
            <CheckboxField
              id="accept_disclaimer"
              label={t("auth.fields.disclaimer.label")}
              checked={values.accept_disclaimer}
              onChange={change.accept_disclaimer}
              describedById={DISCLAIMER_TEXT_ID}
              error={e.accept_disclaimer}
            />
          </div>
        </div>

        <div>
          <SubmitButton pending={session.isPending}>
            {session.isPending ? t("auth.signUp.submitting") : t("auth.signUp.submit")}
          </SubmitButton>
        </div>
      </form>
    </AuthLayout>
  );
}

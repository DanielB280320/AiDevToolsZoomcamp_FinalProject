import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { logIn, useStartSession } from "../api/session";
import {
  EMAIL_MAX_LENGTH,
  type FormErrors,
  firstErrorField,
  PASSWORD_MAX_LENGTH,
  problemToFormErrors,
  SIGN_IN_FIELDS,
  type SignInField,
  type SignInValues,
  validateSignIn,
} from "../auth/forms";
import { AuthLayout } from "../components/AuthLayout";
import { FormAlert, SubmitButton, TextField } from "../components/form/fields";
import { useFocusAfterRender } from "../components/form/useFocusAfterRender";
import { paths } from "../paths";

const FORM_ALERT_ID = "sign-in-error";

export function SignInPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const focus = useFocusAfterRender();
  const session = useStartSession(logIn);

  const [values, setValues] = useState<SignInValues>({ email: "", password: "" });
  const [errors, setErrors] = useState<FormErrors<SignInField>>({ fields: {} });

  const set = (field: SignInField) => (value: string) => setValues((previous) => ({ ...previous, [field]: value }));
  const change = { email: set("email"), password: set("password") };

  const showErrors = (next: FormErrors<SignInField>) => {
    setErrors(next);
    focus(firstErrorField(SIGN_IN_FIELDS, next.fields) ?? FORM_ALERT_ID);
  };

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (session.isPending) return;

    const fieldErrors = validateSignIn(values, t);
    if (Object.keys(fieldErrors).length > 0) {
      showErrors({ fields: fieldErrors });
      return;
    }
    setErrors({ fields: {} });

    try {
      await session.mutateAsync({ email: values.email.trim(), password: values.password });
      navigate(paths.today, { replace: true });
    } catch (error) {
      showErrors(problemToFormErrors(error, SIGN_IN_FIELDS, t));
    }
  };

  return (
    <AuthLayout
      title={t("auth.signIn.title")}
      lead={t("auth.signIn.lead")}
      switchPrompt={t("auth.signIn.switchPrompt")}
      switchLink={t("auth.signIn.switchLink")}
      switchTo={paths.signUp}
    >
      <form noValidate onSubmit={onSubmit} aria-label={t("auth.signIn.title")} className="flex flex-col gap-6">
        {errors.form && <FormAlert id={FORM_ALERT_ID}>{errors.form}</FormAlert>}

        <TextField
          id="email"
          type="email"
          label={t("auth.fields.email.label")}
          value={values.email}
          onChange={change.email}
          autoComplete="email"
          maxLength={EMAIL_MAX_LENGTH}
          error={errors.fields.email}
        />
        <TextField
          id="password"
          type="password"
          label={t("auth.fields.password.label")}
          value={values.password}
          onChange={change.password}
          autoComplete="current-password"
          maxLength={PASSWORD_MAX_LENGTH}
          error={errors.fields.password}
        />

        <div>
          <SubmitButton pending={session.isPending}>
            {session.isPending ? t("auth.signIn.submitting") : t("auth.signIn.submit")}
          </SubmitButton>
        </div>
      </form>
    </AuthLayout>
  );
}

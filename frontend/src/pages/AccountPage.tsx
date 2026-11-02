import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { useDeleteAccount, useExportData } from "../api/account";
import { isApiError } from "../api/errors";
import { rowErrors, useImportWorkouts } from "../api/importWorkouts";
import { FormAlert, SubmitButton, TextField } from "../components/form/fields";
import { paths } from "../paths";

const PASSWORD_MAX_LENGTH = 128;

function ExportSection() {
  const { t } = useTranslation();
  const exportData = useExportData();
  return (
    <section aria-labelledby="export-title" className="border-t-2 border-iron/20 pt-6">
      <h2 id="export-title" className="font-display text-step-2 font-bold">
        {t("account.export.title")}
      </h2>
      <p className="mt-2 text-slate">{t("account.export.lead")}</p>
      <button
        type="button"
        onClick={() => {
          if (!exportData.isPending) exportData.mutate();
        }}
        aria-disabled={exportData.isPending || undefined}
        className="mt-4 min-h-12 rounded-md bg-spruce px-6 py-3 font-semibold text-chalk hover:bg-spruce-dark aria-disabled:opacity-75"
      >
        {exportData.isPending ? t("account.export.exporting") : t("account.export.button")}
      </button>
      {exportData.isError && (
        <p role="alert" className="mt-3 font-semibold text-alert">
          {t("account.export.failed")}
        </p>
      )}
    </section>
  );
}

function ImportSection() {
  const { t } = useTranslation();
  const importer = useImportWorkouts();
  const [file, setFile] = useState<File | null>(null);
  const [missing, setMissing] = useState(false);

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (importer.isPending) return;
    if (file === null) {
      setMissing(true);
      return;
    }
    setMissing(false);
    importer.mutate(file);
  };

  const problem = importer.isError && isApiError(importer.error) ? importer.error.problem : null;
  const rows = problem?.code === "invalid_import" ? rowErrors(problem.fieldErrors) : [];
  let failure: string | null = null;
  if (importer.isError && rows.length === 0) {
    failure =
      problem?.code === "file_too_large"
        ? t("account.import.tooLarge")
        : problem?.code === "too_many_rows"
          ? t("account.import.tooManyRows")
          : t("account.import.failed");
  }

  return (
    <section aria-labelledby="import-title" className="border-t-2 border-iron/20 pt-6">
      <h2 id="import-title" className="font-display text-step-2 font-bold">
        {t("account.import.title")}
      </h2>
      <p className="mt-2 text-slate">{t("account.import.lead")}</p>
      <form noValidate onSubmit={onSubmit} aria-label={t("account.import.title")} className="mt-4 flex flex-col gap-4">
        <div>
          <label htmlFor="import-file" className="font-semibold">
            {t("account.import.file")}
          </label>
          <input
            id="import-file"
            type="file"
            accept=".csv,text/csv"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              setMissing(false);
              importer.reset();
            }}
            aria-invalid={missing || undefined}
            aria-describedby={missing ? "import-file-error" : undefined}
            className="mt-1.5 block w-full"
          />
          {missing && (
            <p id="import-file-error" className="mt-1.5 text-step--1 font-semibold text-alert">
              {t("account.import.chooseFile")}
            </p>
          )}
        </div>
        <div>
          <SubmitButton pending={importer.isPending}>
            {importer.isPending ? t("account.import.importing") : t("account.import.button")}
          </SubmitButton>
        </div>
      </form>
      {importer.isSuccess && (
        <p role="status" className="mt-3 font-semibold text-spruce-dark">
          {t("account.import.done", { imported: importer.data.imported, skipped: importer.data.skipped })}
        </p>
      )}
      {rows.length > 0 && (
        <div role="alert" className="mt-3 text-alert">
          <p className="font-semibold">{t("account.import.rowsHeading")}</p>
          <ul className="mt-1 list-disc pl-6">
            {rows.map((error) => (
              <li key={`${error.row}-${error.reason}`}>
                {error.row === null ? error.reason : t("account.import.row", { row: error.row, reason: error.reason })}
              </li>
            ))}
          </ul>
        </div>
      )}
      {failure !== null && (
        <p role="alert" className="mt-3 font-semibold text-alert">
          {failure}
        </p>
      )}
    </section>
  );
}

function DeleteSection() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const remove = useDeleteAccount(() => navigate(paths.signIn, { replace: true }));
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [missing, setMissing] = useState(false);

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (remove.isPending) return;
    if (password === "") {
      setMissing(true);
      return;
    }
    setMissing(false);
    remove.mutate(password);
  };

  const wrong = remove.isError && isApiError(remove.error) && remove.error.status === 403;

  return (
    <section aria-labelledby="delete-title" className="border-t-2 border-iron/20 pt-6">
      <h2 id="delete-title" className="font-display text-step-2 font-bold">
        {t("account.delete.title")}
      </h2>
      <p className="mt-2 text-slate">{t("account.delete.lead")}</p>
      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="mt-4 min-h-12 rounded-md border-2 border-alert px-6 py-3 font-semibold text-alert hover:bg-alert hover:text-chalk"
        >
          {t("account.delete.open")}
        </button>
      ) : (
        <form noValidate onSubmit={onSubmit} aria-label={t("account.delete.formLabel")} className="mt-4 flex flex-col gap-4">
          <p className="font-semibold">{t("account.delete.confirmLead")}</p>
          {remove.isError && (
            <FormAlert id="delete-error">{wrong ? t("account.delete.wrongPassword") : t("account.delete.failed")}</FormAlert>
          )}
          <TextField
            id="delete-password"
            type="password"
            label={t("account.delete.password")}
            value={password}
            onChange={setPassword}
            autoComplete="current-password"
            maxLength={PASSWORD_MAX_LENGTH}
            error={missing ? t("account.delete.required") : undefined}
          />
          <div className="flex flex-wrap gap-3">
            <SubmitButton pending={remove.isPending}>
              {remove.isPending ? t("account.delete.submitting") : t("account.delete.submit")}
            </SubmitButton>
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                setPassword("");
                remove.reset();
              }}
              className="min-h-12 rounded-md border-2 border-iron/40 px-6 py-3 font-semibold"
            >
              {t("account.delete.cancel")}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

/** Data ownership (F18): export my data, delete my account. */
export function AccountPage() {
  const { t } = useTranslation();
  return (
    <article className="flex max-w-[40rem] flex-col gap-8">
      <h1 className="font-display text-step-4 font-bold">{t("account.title")}</h1>
      <ExportSection />
      <ImportSection />
      <DeleteSection />
    </article>
  );
}

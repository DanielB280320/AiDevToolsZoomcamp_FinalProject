import { useTranslation } from "react-i18next";

import { BUTTON, PRIMARY } from "./fields";

interface Props {
  dirty: boolean;
  pending: boolean;
  conflict: boolean;
  /** The other tab has unsaved edits: saving now would replace them (plan versions renew ids). */
  blocked: boolean;
  failed: boolean;
  invalid?: boolean;
  onSave: () => void;
  onDiscard: () => void;
}

/** Save and discard buttons with their status messages, shared by both editors. */
export function SaveBar({ dirty, pending, conflict, blocked, failed, invalid = false, onSave, onDiscard }: Props) {
  const { t } = useTranslation();
  return (
    <div className="sticky bottom-0 mt-6 border-t-4 border-iron bg-chalk py-3">
      <div className="flex flex-wrap gap-3">
        <button type="button" onClick={onSave} disabled={!dirty || pending || blocked} className={PRIMARY}>
          {pending ? t("plan.saving") : conflict ? t("plan.saveOverLatest") : t("plan.save")}
        </button>
        <button type="button" onClick={onDiscard} disabled={!dirty || pending} className={BUTTON}>
          {t("plan.discard")}
        </button>
      </div>
      {blocked && <p className="mt-2 text-step--1 text-slate">{t("plan.otherTabUnsaved")}</p>}
      {invalid && (
        <p role="alert" className="mt-2 font-semibold text-alert">
          {t("plan.invalid")}
        </p>
      )}
      {failed && (
        <p role="alert" className="mt-2 font-semibold text-alert">
          {t("plan.saveFailed")}
        </p>
      )}
    </div>
  );
}

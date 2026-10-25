import { useTranslation } from "react-i18next";

/** Loading and error states shared by the calendar pages. */
export function QueryState({
  isPending,
  isError,
  onRetry,
}: {
  isPending: boolean;
  isError: boolean;
  onRetry: () => void;
}) {
  const { t } = useTranslation();
  if (isPending) {
    return (
      <p role="status" className="text-step-1 text-slate">
        {t("calendar.loading")}
      </p>
    );
  }
  if (!isError) return null;
  return (
    <div role="alert" className="max-w-[38rem] border-l-4 border-alert pl-4">
      <p className="text-step-1 font-semibold">{t("calendar.loadFailed")}</p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-4 min-h-12 rounded-md bg-spruce px-5 py-3 font-semibold text-chalk hover:bg-spruce-dark"
      >
        {t("session.retry")}
      </button>
    </div>
  );
}

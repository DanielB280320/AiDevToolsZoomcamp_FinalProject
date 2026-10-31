import type { UseQueryResult } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { isApiError } from "../../api/errors";
import { QueryState } from "../calendar/QueryState";

/** The standard forbidden state: the API refused access (`403`, e.g. `not_linked`, D41/D76(8)). */
export function ForbiddenState() {
  const { t } = useTranslation();
  return (
    <div role="alert" className="max-w-[38rem] border-l-4 border-alert pl-4">
      <p className="font-semibold">{t("charts.forbidden.title")}</p>
      <p className="text-slate">{t("charts.forbidden.detail")}</p>
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="border-l-4 border-line pl-3 text-slate">{children}</p>;
}

/**
 * Renders the loading, forbidden and error states of a chart query; `children` get the data.
 * `isEmpty` shows the empty-state message instead (F15.3).
 */
export function ChartState<T>({
  query,
  isEmpty,
  emptyMessage,
  children,
}: {
  query: UseQueryResult<T>;
  isEmpty: (data: T) => boolean;
  emptyMessage: string;
  children: (data: T) => ReactNode;
}) {
  if (query.isError && isApiError(query.error) && query.error.status === 403) return <ForbiddenState />;
  if (!query.data) {
    return <QueryState isPending={query.isPending} isError={query.isError} onRetry={() => void query.refetch()} />;
  }
  if (isEmpty(query.data)) return <EmptyState>{emptyMessage}</EmptyState>;
  return <>{children(query.data)}</>;
}

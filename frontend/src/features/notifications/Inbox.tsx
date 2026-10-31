import { useTranslation } from "react-i18next";

import {
  type AppNotification,
  useMarkAllNotificationsRead,
  useNotificationInbox,
} from "../../api/notifications";
import { useCachedMe } from "../../api/session";
import { QueryState } from "../calendar/QueryState";
import { textKey } from "./model";
import { useNotificationActions } from "./useOpenNotification";

function Row({ notification, onOpen }: { notification: AppNotification; onOpen: () => void }) {
  const { t, i18n } = useTranslation();
  const me = useCachedMe();
  const unread = notification.read_at === null;
  const when = new Intl.DateTimeFormat(i18n.language, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: me?.timezone,
  }).format(new Date(notification.created_at));
  return (
    <li data-unread={unread} className={`border-b border-line ${unread ? "border-l-4 border-l-plate bg-white" : ""}`}>
      <button
        type="button"
        onClick={onOpen}
        className="flex min-h-11 w-full flex-col gap-1 px-3 py-3 text-left"
      >
        <span className={unread ? "font-bold" : "text-slate"}>
          {unread && <span className="mr-2 rounded bg-iron px-1.5 py-0.5 text-step--1 text-chalk">{t("notifications.unreadTag")}</span>}
          {t(textKey(notification.type) as never)}
        </span>
        <time dateTime={notification.created_at} className="text-step--1 text-slate">
          {when}
        </time>
      </button>
    </li>
  );
}

/** The inbox page body (F17.2): newest first, load more, mark all read. */
export function Inbox() {
  const { t } = useTranslation();
  const inbox = useNotificationInbox();
  const markAll = useMarkAllNotificationsRead();
  const actions = useNotificationActions();

  if (!inbox.data) {
    return <QueryState isPending={inbox.isPending} isError={inbox.isError} onRetry={() => void inbox.refetch()} />;
  }
  const items = inbox.data.pages.flatMap((page) => page.items);
  const unreadCount = inbox.data.pages[0]?.unread_count ?? 0;

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p role="status" className="text-slate">
          {t("notifications.inbox.unreadCount", { count: unreadCount })}
        </p>
        {unreadCount > 0 && (
          <button
            type="button"
            disabled={markAll.isPending}
            onClick={() => markAll.mutate()}
            className="min-h-11 rounded-md border-2 border-iron px-4 py-2 font-semibold hover:bg-iron hover:text-chalk"
          >
            {t("notifications.inbox.markAll")}
          </button>
        )}
      </div>
      {(markAll.isError || actions.isError) && (
        <p role="alert" className="mt-3 border-l-4 border-alert pl-3">
          {t("notifications.actionFailed")}
        </p>
      )}
      {inbox.isError && (
        <p role="alert" className="mt-3 border-l-4 border-alert pl-3">
          {t("calendar.loadFailed")}
        </p>
      )}
      {items.length === 0 ? (
        <p className="mt-6 border-l-4 border-line pl-3 text-slate">{t("notifications.inbox.empty")}</p>
      ) : (
        <ul className="mt-4 border-t border-line">
          {items.map((n) => (
            <Row key={n.id} notification={n} onOpen={() => actions.open(n)} />
          ))}
        </ul>
      )}
      {inbox.hasNextPage && (
        <button
          type="button"
          disabled={inbox.isFetchingNextPage}
          onClick={() => void inbox.fetchNextPage()}
          className="mt-4 min-h-11 rounded-md bg-spruce px-5 py-2 font-semibold text-chalk hover:bg-spruce-dark"
        >
          {t("notifications.inbox.loadMore")}
        </button>
      )}
    </>
  );
}

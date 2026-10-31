import { useTranslation } from "react-i18next";

import { Inbox } from "../features/notifications/Inbox";

/** Notification inbox (F17.2), reached from the header bell. */
export function NotificationsPage() {
  const { t } = useTranslation();
  return (
    <article className="max-w-[40rem]">
      <h1 className="font-display text-step-4 font-bold">{t("notifications.title")}</h1>
      <div className="mt-4">
        <Inbox />
      </div>
    </article>
  );
}

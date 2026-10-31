import { useId } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { useUnreadNotifications } from "../../api/notifications";
import { paths } from "../../paths";
import { BANNER_TYPES, MAX_BANNERS, textKey } from "./model";
import { useNotificationActions } from "./useOpenNotification";

/** Unread suggestion / removal notifications as banners on Today, at most 3 then "See all" (D79.3). */
export function TodayBanners() {
  const { t } = useTranslation();
  const headingId = useId();
  const unread = useUnreadNotifications();
  const actions = useNotificationActions();
  if (!unread.data) return null;

  const eligible = unread.data.items.filter((n) => BANNER_TYPES.includes(n.type));
  if (eligible.length === 0) return null;
  const shown = eligible.slice(0, MAX_BANNERS);
  const more = eligible.length > MAX_BANNERS || unread.data.next_cursor !== null;

  return (
    <section aria-labelledby={headingId} className="mt-6">
      <h2 id={headingId} className="sr-only">
        {t("notifications.banners.title")}
      </h2>
      <ul className="flex flex-col gap-3">
        {shown.map((n) => (
          <li key={n.id} data-testid="notification-banner" className="border-l-4 border-plate bg-white p-3">
            <p className="font-semibold">{t(textKey(n.type) as never)}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => actions.open(n)}
                className="min-h-11 rounded-md bg-spruce px-4 py-2 font-semibold text-chalk hover:bg-spruce-dark"
              >
                {t("notifications.banners.open")}
              </button>
              <button
                type="button"
                onClick={() => actions.dismiss(n)}
                className="min-h-11 rounded-md border-2 border-iron px-4 py-2 font-semibold hover:bg-iron hover:text-chalk"
              >
                {t("notifications.banners.dismiss")}
              </button>
            </div>
          </li>
        ))}
      </ul>
      {actions.isError && (
        <p role="alert" className="mt-2 text-alert">
          {t("notifications.actionFailed")}
        </p>
      )}
      {more && (
        <Link to={paths.notifications} className="mt-3 inline-flex min-h-11 items-center font-semibold underline">
          {t("notifications.banners.seeAll")}
        </Link>
      )}
    </section>
  );
}

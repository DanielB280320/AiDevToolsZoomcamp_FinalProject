import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { paths } from "../../paths";

/** Header bell: link to the inbox with the unread count in its accessible name (F17). */
export function Bell({ unread }: { unread: number }) {
  const { t } = useTranslation();
  const label = unread > 0 ? t("notifications.bell.unread", { count: unread }) : t("notifications.bell.none");
  return (
    <Link
      to={paths.notifications}
      aria-label={label}
      className="relative inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border-2 border-chalk/60 text-chalk hover:border-chalk"
    >
      <svg aria-hidden="true" viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M6 9a6 6 0 1 1 12 0c0 6 2 7 2 7H4s2-1 2-7Z" />
        <path d="M10 20a2 2 0 0 0 4 0" />
      </svg>
      {unread > 0 && (
        <span
          aria-hidden="true"
          data-testid="bell-badge"
          className="absolute -right-2 -top-2 min-w-5 rounded-full bg-plate px-1 text-center text-step--1 font-bold leading-5 text-iron"
        >
          {unread > 99 ? t("notifications.bell.overflow") : unread}
        </span>
      )}
    </Link>
  );
}

import { useTranslation } from "react-i18next";
import { NavLink } from "react-router";

import { paths } from "../../paths";

const TABS = [
  { tail: "", key: "today", end: true },
  { tail: "/week", key: "week", end: false },
  { tail: "/month", key: "month", end: false },
  { tail: "/body", key: "body", end: false },
  { tail: "/plan", key: "plan", end: false },
  { tail: "/progress", key: "progress", end: false },
  { tail: "/profile", key: "profile", end: false },
] as const;

/** Tabs of the coach context. The strip scrolls inside itself on a phone, never the page. */
export function ClientNav({ athleteId }: { athleteId: string }) {
  const { t } = useTranslation();
  return (
    <nav aria-label={t("coach.client.navLabel")} className="mb-6">
      <ul className="flex overflow-x-auto border-b-4 border-iron">
        {TABS.map(({ tail, key, end }) => (
          <li key={key} className="flex-1 shrink-0 sm:flex-none">
            <NavLink
              to={paths.coachClient(athleteId, tail)}
              end={end}
              className={({ isActive }) =>
                `flex min-h-12 items-center justify-center px-3 font-display text-step-1 font-bold no-underline sm:min-w-24 sm:px-4 ${
                  isActive ? "bg-iron text-chalk" : "text-iron hover:bg-line"
                }`
              }
            >
              {t(`coach.client.tabs.${key}`)}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}

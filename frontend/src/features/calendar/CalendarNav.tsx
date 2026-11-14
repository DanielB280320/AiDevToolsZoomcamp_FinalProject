import { useTranslation } from "react-i18next";
import { NavLink } from "react-router";

import { useActiveTabInView } from "../../lib/useActiveTabInView";
import { paths } from "../../paths";

const TABS = [
  { to: paths.today, key: "today" },
  { to: paths.week, key: "week" },
  { to: paths.month, key: "month" },
  { to: paths.body, key: "body" },
  { to: paths.plan, key: "plan" },
  { to: paths.progress, key: "progress" },
  { to: paths.coach, key: "coach" },
] as const;

/**
 * Today / Week / Month switcher, shown at the top of each calendar page (thumb-sized on mobile).
 * The tabs share the width; on a narrow screen the strip scrolls sideways without a scrollbar (D100).
 */
export function CalendarNav() {
  const { t } = useTranslation();
  const strip = useActiveTabInView();
  return (
    <nav aria-label={t("calendar.nav.label")} className="mb-6">
      <ul ref={strip} className="no-scrollbar flex overflow-x-auto border-b-4 border-iron">
        {TABS.map(({ to, key }) => (
          <li key={key} className="flex-1 shrink-0">
            <NavLink
              to={to}
              className={({ isActive }) =>
                `flex min-h-12 items-center justify-center whitespace-nowrap px-3 font-display text-step-1 font-bold no-underline ${
                  isActive ? "bg-iron text-chalk" : "text-iron hover:bg-line"
                }`
              }
            >
              {t(`calendar.nav.${key}`)}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}

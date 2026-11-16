import { useTranslation } from "react-i18next";
import { NavLink } from "react-router";

import { useActiveTabInView } from "../../lib/useActiveTabInView";
import { paths } from "../../paths";
import { TAB_STRIP, tabClass } from "../../components/tabs";

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
      <ul ref={strip} className={`no-scrollbar overflow-x-auto ${TAB_STRIP}`}>
        {TABS.map(({ to, key }) => (
          <li key={key} className="flex-1 shrink-0">
            <NavLink
              to={to}
              className={({ isActive }) => tabClass(isActive, "whitespace-nowrap px-3")}
            >
              {t(`calendar.nav.${key}`)}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}

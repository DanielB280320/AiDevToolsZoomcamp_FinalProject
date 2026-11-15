import { useTranslation } from "react-i18next";
import { NavLink } from "react-router";

import { paths } from "../../paths";
import { TAB_STRIP, tabClass } from "../../components/tabs";

/** Coach navigation: the client list and the coach profile with link requests (F16, D81). */
export function CoachNav() {
  const { t } = useTranslation();
  const tabs = [
    { to: paths.coachClients, key: "clients", end: false },
    { to: paths.coach, key: "profile", end: true },
  ] as const;
  return (
    <nav aria-label={t("coach.nav.label")} className="mb-6">
      <ul className={TAB_STRIP}>
        {tabs.map(({ to, key, end }) => (
          <li key={key} className="flex-1 sm:flex-none">
            <NavLink
              to={to}
              end={end}
              className={({ isActive }) => tabClass(isActive, "px-3 sm:min-w-32 sm:px-5")}
            >
              {t(`coach.nav.${key}`)}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}

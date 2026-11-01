import { useTranslation } from "react-i18next";
import { NavLink } from "react-router";

import { paths } from "../../paths";

/** Coach navigation: the client list and the coach profile with link requests (F16, D81). */
export function CoachNav() {
  const { t } = useTranslation();
  const tabs = [
    { to: paths.coachClients, key: "clients", end: false },
    { to: paths.coach, key: "profile", end: true },
  ] as const;
  return (
    <nav aria-label={t("coach.nav.label")} className="mb-6">
      <ul className="flex border-b-4 border-iron">
        {tabs.map(({ to, key, end }) => (
          <li key={key} className="flex-1 sm:flex-none">
            <NavLink
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex min-h-12 items-center justify-center px-3 font-display text-step-1 font-bold no-underline sm:min-w-32 sm:px-5 ${
                  isActive ? "bg-iron text-chalk" : "text-iron hover:bg-line"
                }`
              }
            >
              {t(`coach.nav.${key}`)}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}

import { useTranslation } from "react-i18next";
import { Link } from "react-router";

/** Previous / current / next links for the Week and Month views. */
export function RangeControls({
  title,
  prevTo,
  nextTo,
  currentTo,
  prevLabel,
  nextLabel,
}: {
  title: string;
  prevTo: string;
  nextTo: string;
  currentTo: string;
  prevLabel: string;
  nextLabel: string;
}) {
  const { t } = useTranslation();
  const button =
    "inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border-2 border-iron px-3 font-semibold text-iron no-underline hover:bg-line";
  return (
    <div className="mb-4 flex items-center justify-between gap-2">
      <Link to={prevTo} aria-label={prevLabel} className={button}>
        <span aria-hidden="true">‹</span>
      </Link>
      <div className="text-center">
        <h1 className="font-display text-step-2 font-bold leading-tight">{title}</h1>
        <Link to={currentTo} className="text-step--1 font-semibold text-spruce underline underline-offset-4">
          {t("calendar.range.current")}
        </Link>
      </div>
      <Link to={nextTo} aria-label={nextLabel} className={button}>
        <span aria-hidden="true">›</span>
      </Link>
    </div>
  );
}

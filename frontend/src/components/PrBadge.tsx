import { useTranslation } from "react-i18next";

const GLYPH = "★";

/** Personal-record badge (F15, D88). Glyph and text both carry the meaning. */
export function PrBadge() {
  const { t } = useTranslation();
  return (
    <span
      data-testid="pr-badge"
      className="inline-flex items-center gap-1 rounded-sm bg-plate px-1.5 py-0.5 text-step--1 font-semibold leading-none text-iron"
    >
      <span aria-hidden="true">{GLYPH}</span>
      {t("workout.pr")}
    </span>
  );
}

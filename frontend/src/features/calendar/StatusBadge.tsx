import { useTranslation } from "react-i18next";

import type { BadgeKind } from "./status";

const STYLE: Record<BadgeKind, { glyph: string; className: string }> = {
  done: { glyph: "✓", className: "bg-spruce text-chalk" },
  partial: { glyph: "◐", className: "bg-plate text-iron" },
  missed: { glyph: "✕", className: "bg-alert text-chalk" },
  rest: { glyph: "–", className: "bg-line text-iron" },
  planned: { glyph: "○", className: "border-2 border-iron bg-chalk text-iron" },
};

/** Status chip. The glyph and the label both carry the meaning, so colour is never the only cue. */
export function StatusBadge({ kind, compact = false }: { kind: BadgeKind; compact?: boolean }) {
  const { t } = useTranslation();
  const { glyph, className } = STYLE[kind];
  const label = t(`calendar.status.${kind}`);
  return (
    <span
      data-status={kind}
      className={`inline-flex items-center justify-center gap-1 rounded-sm px-1.5 py-0.5 text-step--1 font-semibold leading-none ${className}`}
    >
      <span aria-hidden="true">{glyph}</span>
      {compact ? <span className="sr-only">{label}</span> : label}
    </span>
  );
}

import type { ReactNode } from "react";

import { ChevronDownIcon } from "../../components/icons";

/**
 * One plan day as a collapsible row (D105): the header is a button with the chevron, the day title and a
 * short summary; the move and remove controls stay next to it. The content stays mounted while collapsed
 * (hidden), so a draft typed in a collapsed day is never lost.
 */
export function DayRow({
  id,
  open,
  onToggle,
  title,
  summary,
  actions,
  note,
  children,
}: {
  id: string;
  open: boolean;
  onToggle: () => void;
  title: string;
  summary: string;
  actions?: ReactNode;
  note?: ReactNode;
  children: ReactNode;
}) {
  return (
    <li
      aria-labelledby={`${id}-title`}
      className="border-l-4 border-plate pl-3"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 id={`${id}-title`} className="min-w-0 flex-1">
          <button
            type="button"
            id={`${id}-toggle`}
            aria-expanded={open}
            aria-controls={`${id}-content`}
            onClick={onToggle}
            className="flex min-h-12 w-full min-w-0 items-start gap-2 text-left hover:text-spruce"
          >
            <ChevronDownIcon
              className={`mt-1 size-6 text-spruce transition-transform ${open ? "rotate-180" : ""}`}
            />
            <span className="min-w-0">
              <span className="block break-words font-display text-step-2 font-bold">
                {title}
              </span>{" "}
              <span className="block text-step--1 font-normal text-slate">
                {summary}
              </span>
            </span>
          </button>
        </h3>
        {actions && <div className="flex shrink-0 gap-1">{actions}</div>}
      </div>
      {note}
      <div id={`${id}-content`} hidden={!open}>
        {children}
      </div>
    </li>
  );
}

import type { ReactNode } from "react";

type IconProps = { className?: string };

/** Decorative line icon: always next to a text label, so it is hidden from assistive technology. */
function Icon({
  className = "size-6",
  children,
}: IconProps & { children: ReactNode }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className={`shrink-0 ${className}`}
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {children}
    </svg>
  );
}

/** Energy, calories burned. */
export function FlameIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.07-2.14-.22-4.05 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.15.43-2.29 1-3a2.5 2.5 0 0 0 2.5 2.5Z" />
    </Icon>
  );
}

/** Meals, calories eaten. */
export function UtensilsIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3 2v7a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2V2" />
      <path d="M7 2v20" />
      <path d="M21 15V2a5 5 0 0 0-5 5v6a2 2 0 0 0 2 2h3Zm0 0v7" />
    </Icon>
  );
}

/** Training. */
export function DumbbellIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M6.5 6v12" />
      <path d="M17.5 6v12" />
      <path d="M3 9v6" />
      <path d="M21 9v6" />
      <path d="M6.5 12h11" />
    </Icon>
  );
}

/** Suggestions. */
export function LightbulbIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5" />
      <path d="M9 18h6" />
      <path d="M10 22h4" />
    </Icon>
  );
}

/** Recent decisions. */
export function CheckCircleIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="10" />
      <path d="m8.5 12 2.5 2.5 4.5-5" />
    </Icon>
  );
}

/** Coach notes. */
export function NoteIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2Z" />
    </Icon>
  );
}

/** Energy balance. */
export function ScaleIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z" />
      <path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z" />
      <path d="M7 21h10" />
      <path d="M12 3v18" />
      <path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2" />
    </Icon>
  );
}

/** Target balance. */
export function TargetIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="10" />
      <circle cx="12" cy="12" r="6" />
      <circle cx="12" cy="12" r="2" />
    </Icon>
  );
}

/** Marks a row that opens and closes; rotate it with a class when open. */
export function ChevronDownIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="m6 9 6 6 6-6" />
    </Icon>
  );
}

/** Plan history: earlier versions of the plan. */
export function HistoryIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
      <path d="M3 3v5h5" />
      <path d="M12 7v5l3 2" />
    </Icon>
  );
}

/** The current plan: a clipboard. */
export function ClipboardIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="8" y="2" width="8" height="4" rx="1" />
      <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
      <path d="M9 12h6" />
      <path d="M9 16h6" />
    </Icon>
  );
}

/** Create something new, such as a new plan. */
export function PlusCircleIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="10" />
      <path d="M12 8v8" />
      <path d="M8 12h8" />
    </Icon>
  );
}

/** Day checklist: what is done and what is still open. */
export function ChecklistIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="m3 6 1.5 1.5L7 5" />
      <path d="m3 12 1.5 1.5L7 11" />
      <path d="m3 18 1.5 1.5L7 17" />
      <path d="M11 6h10" />
      <path d="M11 12h10" />
      <path d="M11 18h10" />
    </Icon>
  );
}

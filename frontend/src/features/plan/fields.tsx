import type { ReactNode } from "react";

export const BUTTON = "min-h-12 rounded-control border border-edge hover:border-slate px-4 font-semibold hover:bg-line disabled:opacity-60";
export const PRIMARY = "min-h-12 rounded-control bg-spruce px-4 font-semibold text-chalk hover:bg-spruce-dark active:bg-spruce-dark disabled:opacity-60";
export const ICON_BUTTON = "min-h-12 min-w-12 rounded-control border border-edge hover:border-slate px-2 font-semibold hover:bg-line disabled:opacity-40";
const CONTROL =
  "mt-1 block min-h-12 w-full rounded-control border border-edge bg-card px-3 py-2 hover:border-slate aria-[invalid=true]:border-alert";
/** Compact field (D112): a small label over a 44 px control, for rows of several fields. */
const COMPACT_CONTROL =
  "mt-0.5 block min-h-11 w-full rounded-control border border-edge bg-card px-2 py-1 hover:border-slate aria-[invalid=true]:border-alert";
const LABEL = "block font-semibold";
const COMPACT_LABEL = "block text-step--1 font-semibold text-slate";
/** Label kept for assistive technology only, when the row already shows what the field is. */
const HIDDEN_LABEL = "sr-only";

export function FieldError({ id, children }: { id: string; children: ReactNode }) {
  return (
    <p id={id} className="mt-1 text-step--1 font-semibold text-alert">
      {children}
    </p>
  );
}

interface BaseProps {
  id: string;
  label: string;
  error?: string | undefined;
  hint?: string;
  /** Small label and a tighter control, for a row of fields (D112). */
  compact?: boolean;
  /** Visually hide the label (it stays the accessible name). */
  labelHidden?: boolean;
  /** Id of a shared hint line the field is described by, in addition to its own hint and error. */
  describedBy?: string;
}

const labelClass = (compact?: boolean, hidden?: boolean) => (hidden ? HIDDEN_LABEL : compact ? COMPACT_LABEL : LABEL);
const joinIds = (...ids: (string | undefined | false)[]) => ids.filter(Boolean).join(" ") || undefined;

export function TextInput({
  id,
  label,
  value,
  onChange,
  error,
  hint,
  inputMode,
  maxLength,
  disabled,
  compact,
  labelHidden,
  describedBy: sharedHint,
}: BaseProps & {
  value: string;
  onChange: (value: string) => void;
  inputMode?: "decimal" | "numeric";
  maxLength?: number;
  disabled?: boolean;
}) {
  const describedBy = joinIds(hint && `${id}-hint`, error && `${id}-error`, sharedHint);
  return (
    <div className="min-w-0">
      <label htmlFor={id} className={labelClass(compact, labelHidden)}>
        {label}
      </label>
      <input
        id={id}
        type="text"
        inputMode={inputMode}
        maxLength={maxLength}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={compact ? COMPACT_CONTROL : CONTROL}
      />
      {hint && (
        <p id={`${id}-hint`} className="mt-1 text-step--1 text-slate">
          {hint}
        </p>
      )}
      {error && <FieldError id={`${id}-error`}>{error}</FieldError>}
    </div>
  );
}

export function SelectInput({
  id,
  label,
  value,
  onChange,
  options,
  error,
  hint,
  compact,
  labelHidden,
  describedBy: sharedHint,
}: BaseProps & {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  const describedBy = joinIds(hint && `${id}-hint`, error && `${id}-error`, sharedHint);
  return (
    <div className="min-w-0">
      <label htmlFor={id} className={labelClass(compact, labelHidden)}>
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={compact ? COMPACT_CONTROL : CONTROL}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      {hint && (
        <p id={`${id}-hint`} className="mt-1 text-step--1 text-slate">
          {hint}
        </p>
      )}
      {error && <FieldError id={`${id}-error`}>{error}</FieldError>}
    </div>
  );
}

export function DateInput({
  id,
  label,
  value,
  onChange,
  max,
  error,
  hint,
}: BaseProps & {
  value: string;
  onChange: (value: string) => void;
  max?: string;
}) {
  const describedBy =
    [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(" ") ||
    undefined;
  return (
    <div className="min-w-0">
      <label htmlFor={id} className="block font-semibold">
        {label}
      </label>
      <input
        id={id}
        type="date"
        value={value}
        max={max}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={CONTROL}
      />
      {hint && (
        <p id={`${id}-hint`} className="mt-1 text-step--1 text-slate">
          {hint}
        </p>
      )}
      {error && <FieldError id={`${id}-error`}>{error}</FieldError>}
    </div>
  );
}

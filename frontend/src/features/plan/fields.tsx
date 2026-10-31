import type { ReactNode } from "react";

export const BUTTON = "min-h-12 rounded-md border-2 border-iron px-4 font-semibold hover:bg-line disabled:opacity-60";
export const PRIMARY = "min-h-12 rounded-md bg-spruce px-4 font-semibold text-chalk hover:bg-spruce-dark disabled:opacity-60";
export const ICON_BUTTON = "min-h-12 min-w-12 rounded-md border-2 border-iron/60 px-2 font-semibold hover:bg-line disabled:opacity-40";
const CONTROL =
  "mt-1 block min-h-12 w-full rounded-md border-2 border-iron/35 bg-white px-3 py-2 hover:border-iron/60 aria-[invalid=true]:border-alert";

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
}

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
}: BaseProps & {
  value: string;
  onChange: (value: string) => void;
  inputMode?: "decimal" | "numeric";
  maxLength?: number;
  disabled?: boolean;
}) {
  const describedBy = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(" ") || undefined;
  return (
    <div className="min-w-0">
      <label htmlFor={id} className="block font-semibold">
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

export function SelectInput({
  id,
  label,
  value,
  onChange,
  options,
  error,
}: BaseProps & { value: string; onChange: (value: string) => void; options: { value: string; label: string }[] }) {
  return (
    <div className="min-w-0">
      <label htmlFor={id} className="block font-semibold">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        className={CONTROL}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      {error && <FieldError id={`${id}-error`}>{error}</FieldError>}
    </div>
  );
}

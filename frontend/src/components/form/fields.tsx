import type { ReactNode } from "react";

/** Ids of the describing elements: hint first, then the error, so both are read out. */
function describedBy(id: string, hint: boolean, error: boolean): string | undefined {
  const ids = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean);
  return ids.length ? ids.join(" ") : undefined;
}

/** Element id to focus for a field (a radio group focuses its first option). */
export function focusTargetId(id: string, firstOption?: string): string {
  return firstOption ? `${id}-${firstOption}` : id;
}

function Hint({ id, children }: { id: string; children: ReactNode }) {
  return (
    <p id={`${id}-hint`} className="mt-1 text-step--1 text-slate">
      {children}
    </p>
  );
}

function FieldError({ id, children }: { id: string; children: ReactNode }) {
  return (
    <p id={`${id}-error`} className="mt-1.5 text-step--1 font-semibold text-alert">
      {children}
    </p>
  );
}

const control =
  "mt-1.5 block min-h-12 w-full rounded-md border-2 bg-white px-3 py-2 text-step-0 text-iron " +
  "border-iron/35 hover:border-iron/60 aria-[invalid=true]:border-alert";

interface TextFieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "email" | "password" | "date";
  hint?: string;
  error?: string;
  autoComplete?: string;
  maxLength?: number;
  max?: string;
}

export function TextField({ id, label, value, onChange, type = "text", hint, error, autoComplete, maxLength, max }: TextFieldProps) {
  return (
    <div>
      <label htmlFor={id} className="block font-semibold">
        {label}
      </label>
      {hint && <Hint id={id}>{hint}</Hint>}
      <input
        id={id}
        name={id}
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        autoComplete={autoComplete}
        maxLength={maxLength}
        max={max}
        required
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, Boolean(hint), Boolean(error))}
        className={control}
      />
      {error && <FieldError id={id}>{error}</FieldError>}
    </div>
  );
}

interface SelectFieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: readonly string[];
  hint?: string;
  error?: string;
}

export function SelectField({ id, label, value, onChange, options, hint, error }: SelectFieldProps) {
  return (
    <div>
      <label htmlFor={id} className="block font-semibold">
        {label}
      </label>
      {hint && <Hint id={id}>{hint}</Hint>}
      <select
        id={id}
        name={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        required
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, Boolean(hint), Boolean(error))}
        className={control}
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
      {error && <FieldError id={id}>{error}</FieldError>}
    </div>
  );
}

export interface Choice<V extends string> {
  value: V;
  label: string;
  detail: string;
}

interface ChoiceFieldProps<V extends string> {
  id: string;
  legend: string;
  value: V | "";
  onChange: (value: V) => void;
  choices: readonly Choice<V>[];
  hint?: string;
  error?: string;
}

/** A radio group drawn as a segmented control. Native radios: arrow keys move the choice. */
export function ChoiceField<V extends string>({ id, legend, value, onChange, choices, hint, error }: ChoiceFieldProps<V>) {
  return (
    <fieldset aria-describedby={describedBy(id, Boolean(hint), Boolean(error))}>
      <legend className="font-semibold">{legend}</legend>
      {hint && <Hint id={id}>{hint}</Hint>}
      <div className="mt-1.5 grid grid-cols-2 gap-2">
        {choices.map((choice) => (
          <label
            key={choice.value}
            htmlFor={`${id}-${choice.value}`}
            className={
              "flex min-h-14 cursor-pointer flex-col justify-center rounded-md border-2 bg-white px-3 py-2 " +
              (error ? "border-alert " : "border-iron/35 hover:border-iron/60 ") +
              "has-[:checked]:border-iron has-[:checked]:bg-iron has-[:checked]:text-chalk " +
              "has-[:focus-visible]:outline-[3px] has-[:focus-visible]:outline-offset-2 " +
              "has-[:focus-visible]:outline-spruce has-[:focus-visible]:outline-solid"
            }
          >
            <input
              id={`${id}-${choice.value}`}
              type="radio"
              name={id}
              value={choice.value}
              checked={value === choice.value}
              onChange={() => onChange(choice.value)}
              required
              className="sr-only"
            />
            <span className="font-display text-step-1 font-semibold leading-tight">{choice.label}</span>
            <span className="text-step--1 opacity-80">{choice.detail}</span>
          </label>
        ))}
      </div>
      {error && <FieldError id={id}>{error}</FieldError>}
    </fieldset>
  );
}

interface CheckboxFieldProps {
  id: string;
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  /** Id of text elsewhere that this checkbox confirms, read out with the label. */
  describedById?: string;
  error?: string;
}

export function CheckboxField({ id, label, checked, onChange, describedById, error }: CheckboxFieldProps) {
  const describedByIds = [describedById, error && `${id}-error`].filter(Boolean).join(" ") || undefined;
  return (
    <div>
      <div className="flex items-start gap-3">
        <input
          id={id}
          name={id}
          type="checkbox"
          checked={checked}
          onChange={(event) => onChange(event.target.checked)}
          required
          aria-invalid={error ? true : undefined}
          aria-describedby={describedByIds}
          className="mt-0.5 size-6 shrink-0 cursor-pointer accent-spruce"
        />
        <label htmlFor={id} className="cursor-pointer font-semibold">
          {label}
        </label>
      </div>
      {error && <FieldError id={id}>{error}</FieldError>}
    </div>
  );
}

/** Problem with the whole form (wrong credentials, rate limit, network). Focused when shown. */
export function FormAlert({ id, children }: { id: string; children: ReactNode }) {
  return (
    <div
      id={id}
      role="alert"
      tabIndex={-1}
      className="border-l-4 border-alert bg-white px-4 py-3 font-semibold text-alert focus:outline-none focus-visible:outline-[3px]"
    >
      {children}
    </div>
  );
}

export function SubmitButton({ children, pending }: { children: ReactNode; pending: boolean }) {
  return (
    <button
      type="submit"
      aria-disabled={pending || undefined}
      className={
        "min-h-12 w-full rounded-md bg-spruce px-6 py-3 text-step-0 font-semibold text-chalk sm:w-auto " +
        "hover:bg-spruce-dark aria-disabled:cursor-progress aria-disabled:opacity-75"
      }
    >
      {children}
    </button>
  );
}

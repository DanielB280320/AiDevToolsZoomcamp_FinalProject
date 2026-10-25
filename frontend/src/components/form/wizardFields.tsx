const control =
  "mt-1.5 block min-h-12 w-full rounded-md border-2 bg-white px-3 py-2 text-step-0 text-iron " +
  "border-iron/35 hover:border-iron/60 aria-[invalid=true]:border-alert";

interface NumberFieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  /** Unit shown next to the input (and read out with the label), e.g. "kg" or "in". */
  unit: string;
  hint?: string;
  error?: string;
}

/** A decimal input with its unit beside it. Text, not `type=number`: no spinners, no locale surprises. */
export function NumberField({ id, label, value, onChange, unit, hint, error }: NumberFieldProps) {
  const describedBy = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(" ") || undefined;
  return (
    <div>
      <label htmlFor={id} className="block font-semibold">
        {label} <span className="font-normal text-slate">({unit})</span>
      </label>
      {hint && (
        <p id={`${id}-hint`} className="mt-1 text-step--1 text-slate">
          {hint}
        </p>
      )}
      <input
        id={id}
        name={id}
        type="text"
        inputMode="decimal"
        autoComplete="off"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={control}
      />
      {error && (
        <p id={`${id}-error`} className="mt-1.5 text-step--1 font-semibold text-alert">
          {error}
        </p>
      )}
    </div>
  );
}

interface MultiChoiceFieldProps<V extends string> {
  id: string;
  legend: string;
  values: readonly V[];
  onToggle: (value: V) => void;
  options: readonly { value: V; label: string }[];
  hint?: string;
  error?: string;
}

/** A checkbox group drawn as toggle chips (preferred weekdays, allergies). */
export function MultiChoiceField<V extends string>({ id, legend, values, onToggle, options, hint, error }: MultiChoiceFieldProps<V>) {
  const describedBy = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(" ") || undefined;
  return (
    <fieldset aria-describedby={describedBy}>
      <legend className="font-semibold">{legend}</legend>
      {hint && (
        <p id={`${id}-hint`} className="mt-1 text-step--1 text-slate">
          {hint}
        </p>
      )}
      <div className="mt-1.5 flex flex-wrap gap-2">
        {options.map((option) => (
          <label
            key={option.value}
            htmlFor={`${id}-${option.value}`}
            className={
              "flex min-h-12 min-w-14 cursor-pointer items-center justify-center rounded-md border-2 bg-white px-3 py-2 font-semibold " +
              (error ? "border-alert " : "border-iron/35 hover:border-iron/60 ") +
              "has-[:checked]:border-iron has-[:checked]:bg-iron has-[:checked]:text-chalk " +
              "has-[:focus-visible]:outline-[3px] has-[:focus-visible]:outline-offset-2 " +
              "has-[:focus-visible]:outline-spruce has-[:focus-visible]:outline-solid"
            }
          >
            <input
              id={`${id}-${option.value}`}
              type="checkbox"
              checked={values.includes(option.value)}
              onChange={() => onToggle(option.value)}
              className="sr-only"
            />
            {option.label}
          </label>
        ))}
      </div>
      {error && (
        <p id={`${id}-error`} className="mt-1.5 text-step--1 font-semibold text-alert">
          {error}
        </p>
      )}
    </fieldset>
  );
}

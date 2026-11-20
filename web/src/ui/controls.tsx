import { type ReactNode, useId } from "react";
import { Button } from "./Button";

interface SwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  /** Read by screen readers; the visible row usually already names the thing. */
  label: string;
  disabled?: boolean;
}

export function Switch({ checked, onChange, label, disabled }: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      className="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
    />
  );
}

interface SegmentedProps<Value extends string> {
  legend: string;
  /** Hide the legend visually when the surrounding text already says what is being chosen. */
  hideLegend?: boolean;
  options: readonly { value: Value; label: ReactNode }[];
  value: Value;
  onChange: (value: Value) => void;
  disabled?: boolean;
}

/** A radio group drawn as one segmented control; arrow keys move the choice, as with any radios. */
export function Segmented<Value extends string>({
  legend,
  hideLegend = false,
  options,
  value,
  onChange,
  disabled,
}: SegmentedProps<Value>) {
  const name = useId();
  return (
    <fieldset className="plain">
      <legend className={hideLegend ? "sr-only" : "label"}>{legend}</legend>
      <div className="segmented">
        {options.map((option) => (
          <label key={option.value}>
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={option.value === value}
              disabled={disabled}
              onChange={() => onChange(option.value)}
            />
            {option.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

interface FieldProps {
  label: ReactNode;
  error?: string | null;
  /** Receives the ids to wire the control to its label and error. */
  children: (ids: { id: string; describedBy: string | undefined; invalid: boolean }) => ReactNode;
}

export function Field({ label, error, children }: FieldProps) {
  const id = useId();
  const errorId = `${id}-error`;
  const describedBy = error ? errorId : undefined;
  return (
    <div className="field">
      <label className="label" htmlFor={id}>
        {label}
      </label>
      {children({ id, describedBy, invalid: Boolean(error) })}
      {error && (
        <span className="error-text" id={errorId} role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

interface PaginationProps {
  offset: number;
  limit: number;
  total: number;
  onChange: (offset: number) => void;
}

export function Pagination({ offset, limit, total, onChange }: PaginationProps) {
  if (total <= limit) return null;
  const last = Math.min(offset + limit, total);
  return (
    <nav className="pagination" aria-label="Pages">
      <span>
        {offset + 1}–{last} of {total}
      </span>
      <span className="row">
        <Button size="sm" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
          Previous
        </Button>
        <Button size="sm" disabled={last >= total} onClick={() => onChange(offset + limit)}>
          Next
        </Button>
      </span>
    </nav>
  );
}

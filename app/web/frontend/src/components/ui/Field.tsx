import type { ReactNode, InputHTMLAttributes, SelectHTMLAttributes } from "react";

export function Field({
  label,
  hint,
  children,
  className = "",
}: {
  label?: ReactNode;
  hint?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={`field ${className}`}>
      {label && <span className="field__label">{label}</span>}
      {children}
      {hint && <span className="field__hint">{hint}</span>}
    </label>
  );
}

interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: ReactNode;
  hint?: ReactNode;
  fieldClassName?: string;
}

export function TextField({ label, hint, fieldClassName, ...rest }: TextFieldProps) {
  return (
    <Field label={label} hint={hint} className={fieldClassName}>
      <input className="input" {...rest} />
    </Field>
  );
}

interface SelectFieldProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: ReactNode;
  hint?: ReactNode;
  options: [string, string][];
  fieldClassName?: string;
}

export function SelectField({
  label,
  hint,
  options,
  fieldClassName,
  ...rest
}: SelectFieldProps) {
  return (
    <Field label={label} hint={hint} className={fieldClassName}>
      <select className="input select" {...rest}>
        {options.map(([value, text]) => (
          <option key={value} value={value}>
            {text}
          </option>
        ))}
      </select>
    </Field>
  );
}

interface CheckboxProps extends InputHTMLAttributes<HTMLInputElement> {
  label: ReactNode;
  hint?: ReactNode;
}

export function Checkbox({ label, hint, ...rest }: CheckboxProps) {
  return (
    <label className="checkbox">
      <input type="checkbox" {...rest} />
      <span className="checkbox__body">
        <span className="checkbox__label">{label}</span>
        {hint && <span className="checkbox__hint">{hint}</span>}
      </span>
    </label>
  );
}

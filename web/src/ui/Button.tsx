import type { ButtonHTMLAttributes } from "react";
import { Icon, type IconName } from "./Icon";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "primary" | "danger" | "ghost";
  size?: "md" | "sm";
  icon?: IconName;
  /** Shows a spinner and blocks further clicks while a request is in flight. */
  busy?: boolean;
}

const VARIANT_CLASS = {
  default: "",
  primary: "btn-primary",
  danger: "btn-danger",
  ghost: "btn-ghost",
} as const;

export function Button({
  variant = "default",
  size = "md",
  icon,
  busy = false,
  type = "button",
  className,
  disabled,
  children,
  ...rest
}: ButtonProps) {
  const classes = ["btn", VARIANT_CLASS[variant], size === "sm" ? "btn-sm" : "", className ?? ""];
  return (
    <button
      // oxlint-disable-next-line react/button-has-type -- the type is always one of the three valid values
      type={type}
      className={classes.filter(Boolean).join(" ")}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      {...rest}
    >
      {busy ? <span className="spinner" aria-hidden="true" /> : icon && <Icon name={icon} size={16} />}
      {children}
    </button>
  );
}

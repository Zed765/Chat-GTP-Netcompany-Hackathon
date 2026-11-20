import type { ReactNode } from "react";
import type { Hue } from "../lib/dataTypes";
import { Icon, type IconName } from "./Icon";

type Tone = "info" | "success" | "warning" | "danger";

const TONES: Record<Tone, { hue: Hue; icon: IconName }> = {
  info: { hue: "blue", icon: "info" },
  success: { hue: "green", icon: "check" },
  warning: { hue: "yellow", icon: "alert" },
  danger: { hue: "red", icon: "block" },
};

interface NoticeProps {
  tone?: Tone;
  title?: ReactNode;
  /** `alert` interrupts a screen reader, `status` waits its turn; omit for static text. */
  role?: "alert" | "status";
  children?: ReactNode;
}

export function Notice({ tone = "info", title, role, children }: NoticeProps) {
  const look = TONES[tone];
  return (
    <div className="notice tinted" data-hue={look.hue} role={role}>
      <Icon name={look.icon} />
      <div className="notice-body">
        {title && <strong>{title}</strong>}
        {children}
      </div>
    </div>
  );
}

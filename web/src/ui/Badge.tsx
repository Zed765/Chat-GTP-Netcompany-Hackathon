import type { ReactNode } from "react";
import type { RowSource, Tier } from "../api/types";
import { type Hue, dataTypeInfo } from "../lib/dataTypes";
import { SOURCES, TIERS } from "../lib/labels";
import { Icon, type IconName } from "./Icon";

interface BadgeProps {
  hue?: Hue;
  icon?: IconName;
  title?: string;
  children: ReactNode;
}

/** A small label. With a hue it is tinted; meaning is always in the text, never the colour alone. */
export function Badge({ hue, icon, title, children }: BadgeProps) {
  return (
    <span className={hue ? "badge tinted" : "badge badge-plain"} data-hue={hue} title={title}>
      {icon && <Icon name={icon} size={13} />}
      {children}
    </span>
  );
}

export function TierBadge({ tier }: { tier: Tier }) {
  return <Badge title={TIERS[tier].detail}>{`${tier} · ${TIERS[tier].label}`}</Badge>;
}

export function SourceBadge({ source }: { source: RowSource }) {
  return <Badge hue={source === "default" ? undefined : "violet"}>{SOURCES[source]}</Badge>;
}

/** A data type by its plain name, in its family's hue, with an optional count. */
export function TypeChip({ type, count }: { type: string; count?: number }) {
  const info = dataTypeInfo(type);
  return (
    <span className="badge tinted" data-hue={info.hue} title={type}>
      {count !== undefined && <span className="strong">{count} ×</span>}
      {info.label}
    </span>
  );
}

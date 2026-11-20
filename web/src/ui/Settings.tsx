import { type ReactNode, useId, useState } from "react";
import { Icon } from "./Icon";

interface SettingsGroupProps {
  title: string;
  /** One sentence for a group whose choices need their words explained. */
  note?: string;
  children: ReactNode;
}

/** A titled list of settings. Every row either changes its setting on the spot or opens to its editor. */
export function SettingsGroup({ title, note, children }: SettingsGroupProps) {
  const titleId = useId();
  return (
    <section className="card settings-group" aria-labelledby={titleId}>
      <h2 id={titleId}>{title}</h2>
      {note && <p className="settings-note">{note}</p>}
      <ul className="settings">{children}</ul>
    </section>
  );
}

/** One setting on one line: its name, then the control that changes it. */
export function Setting({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <li className="setting">
      <span className="setting-label">{label}</span>
      <span className="setting-control">{children}</span>
    </li>
  );
}

/** A message that belongs to the rows around it, such as a failed save. */
export function SettingNote({ children }: { children: ReactNode }) {
  return <li className="setting-note">{children}</li>;
}

interface SettingPanelProps {
  label: string;
  /** What the setting holds now, in a word or a number. */
  value?: ReactNode;
  /** Rendered only while the row is open, so a closed row loads nothing. */
  children: ReactNode;
}

/** A setting too large for one line: the row opens in place to its editor. */
export function SettingPanel({ label, value, children }: SettingPanelProps) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  return (
    <li className="setting-fold">
      <button type="button" className="setting setting-toggle" aria-expanded={open} aria-controls={panelId} onClick={() => setOpen((shown) => !shown)}>
        <span className="setting-label">{label}</span>
        <span className="setting-value">{value}</span>
        <Icon name="chevron-right" size={14} />
      </button>
      <div id={panelId} className="setting-panel" hidden={!open}>
        {open && children}
      </div>
    </li>
  );
}

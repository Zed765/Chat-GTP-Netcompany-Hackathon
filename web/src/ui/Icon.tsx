const PATHS = {
  shield: "M12 3l7 3v5c0 4.5-3 8.2-7 10-4-1.8-7-5.5-7-10V6l7-3z",
  "shield-check": "M12 3l7 3v5c0 4.5-3 8.2-7 10-4-1.8-7-5.5-7-10V6l7-3z M9 12l2.2 2.2L15.5 10",
  check: "M5 12.5l4.5 4.5L19 7.5",
  alert: "M12 4l9 16H3L12 4z M12 10v4.5 M12 17.2v.3",
  block: "M12 3a9 9 0 100 18 9 9 0 000-18z M5.7 5.7l12.6 12.6",
  eye: "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z M12 9a3 3 0 100 6 3 3 0 000-6z",
  mask: "M3 3l18 18 M10.5 5.2c.5-.1 1-.2 1.5-.2 6.4 0 10 7 10 7a17 17 0 01-2.7 3.6 M6.3 6.8C3.6 8.6 2 12 2 12s3.6 7 10 7c1.6 0 3.1-.4 4.3-1.1 M9.9 9.9a3 3 0 004.2 4.2",
  send: "M4 12l16-8-6 16-3-7-7-1z",
  refresh: "M20 11a8 8 0 10-2.3 5.7 M20 4v7h-7",
  upload: "M12 16V4 M7 9l5-5 5 5 M4 20h16",
  trash: "M4 7h16 M9 7V4h6v3 M6 7l1 13h10l1-13 M10 11v6 M14 11v6",
  "chevron-down": "M6 9l6 6 6-6",
  "chevron-right": "M9 6l6 6-6 6",
  sun: "M12 8a4 4 0 100 8 4 4 0 000-8z M12 2v2 M12 20v2 M2 12h2 M20 12h2 M4.9 4.9l1.4 1.4 M17.7 17.7l1.4 1.4 M4.9 19.1l1.4-1.4 M17.7 6.3l1.4-1.4",
  moon: "M20 14.5A8 8 0 019.5 4a8 8 0 1010.5 10.5z",
  menu: "M4 6h16 M4 12h16 M4 18h16",
  close: "M6 6l12 12 M18 6L6 18",
  mail: "M3 6h18v12H3z M3 7l9 6 9-6",
  user: "M12 12a4 4 0 100-8 4 4 0 000 8z M4 20c1.5-4 4.5-5.5 8-5.5s6.5 1.5 8 5.5",
  lock: "M6 11h12v9H6z M8.5 11V8a3.5 3.5 0 017 0v3",
  info: "M12 3a9 9 0 100 18 9 9 0 000-18z M12 11v5 M12 7.8v.3",
  play: "M7 5l12 7-12 7V5z",
  search: "M11 4a7 7 0 100 14 7 7 0 000-14z M16 16l4.5 4.5",
  copy: "M9 9h11v11H9z M5 15H4V4h11v1",
  bot: "M5 9h14v10H5z M12 9V5 M9 13v2 M15 13v2 M2 13v3 M22 13v3",
  tool: "M14.5 6.5a4 4 0 00-5.2 5.2L4 17l3 3 5.3-5.3a4 4 0 005.2-5.2L15 12l-3-3 2.5-2.5z",
  globe: "M12 3a9 9 0 100 18 9 9 0 000-18z M3 12h18 M12 3c2.8 3 2.8 15 0 18 M12 3c-2.8 3-2.8 15 0 18",
  database:
    "M5 6c0-1.7 3.1-3 7-3s7 1.3 7 3-3.1 3-7 3-7-1.3-7-3z M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6 M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3",
  file: "M6 3h8l4 4v14H6z M14 3v4h4",
  list: "M8 6h12 M8 12h12 M8 18h12 M4 6h.5 M4 12h.5 M4 18h.5",
  chart: "M4 20V4 M4 20h16 M8 16v-5 M12 16V8 M16 16v-3",
  policy: "M6 4h12v16H6z M9 8h6 M9 12h6 M9 16h3",
  chat: "M4 5h16v11H9l-5 4V5z",
  inbox: "M4 13l2.5-8h11L20 13v6H4v-6z M4 13h5l1 2h4l1-2h5",
  plus: "M12 5v14 M5 12h14",
  "arrow-right": "M5 12h14 M13 6l6 6-6 6",
  clock: "M12 3a9 9 0 100 18 9 9 0 000-18z M12 7v5l3 2",
  link: "M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1 M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1",
} as const;

export type IconName = keyof typeof PATHS;

interface IconProps {
  name: IconName;
  size?: number;
  /** Set only when the icon stands alone; otherwise the text next to it carries the meaning. */
  label?: string;
}

export function Icon({ name, size = 18, label }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      <path d={PATHS[name]} />
    </svg>
  );
}

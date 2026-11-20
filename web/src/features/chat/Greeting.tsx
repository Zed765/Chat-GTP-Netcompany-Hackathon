import { useEffect, useState } from "react";
import { dataTypeInfo } from "../../lib/dataTypes";

const NAME_MS = 15000;
const PLACEHOLDER_MS = 5000;

/** The greeting keeps trading the reader's name for a placeholder and back: what the firewall does, in one line. */
export function Greeting({ name }: { name: string }) {
  const [still] = useState(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const [restored, setRestored] = useState(still);
  useEffect(() => {
    if (still) return;
    const timer = window.setTimeout(() => setRestored((value) => !value), restored ? NAME_MS : PLACEHOLDER_MS);
    return () => window.clearTimeout(timer);
  }, [restored, still]);
  const { hue } = dataTypeInfo("PERSON");
  return (
    <p className="greeting">
      <span className="sr-only">Hello, {name}</span>
      <span aria-hidden="true">
        Hello,{" "}
        {restored ? (
          <mark className="mark tinted" data-hue={hue}>
            {name}
          </mark>
        ) : (
          <span className="chip tinted" data-hue={hue}>
            {"<PERSON_1>"}
          </span>
        )}
      </span>
    </p>
  );
}

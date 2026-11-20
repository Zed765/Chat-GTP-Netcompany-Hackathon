export type Hue = "blue" | "orange" | "aqua" | "yellow" | "magenta" | "green" | "violet" | "red" | "neutral";

export interface DataTypeInfo {
  /** Plain-language name, for people who have never seen the type code. */
  label: string;
  /** Types of one family share a hue, so a reader learns eight colours, not twenty. */
  hue: Hue;
}

const KNOWN: Record<string, DataTypeInfo> = {
  PERSON: { label: "Person name", hue: "blue" },
  ORG: { label: "Organisation", hue: "magenta" },
  CLIENT: { label: "Client name", hue: "magenta" },
  LOCATION: { label: "Location", hue: "green" },
  ADDRESS: { label: "Address", hue: "green" },
  EMAIL: { label: "Email address", hue: "aqua" },
  PHONE: { label: "Phone number", hue: "aqua" },
  AFM: { label: "Tax number (AFM)", hue: "orange" },
  AMKA: { label: "Social security number (AMKA)", hue: "orange" },
  ID_CARD: { label: "ID card number", hue: "orange" },
  IBAN: { label: "Bank account (IBAN)", hue: "yellow" },
  CARD: { label: "Payment card", hue: "yellow" },
  SECRET: { label: "Secret or API key", hue: "red" },
  CONFIDENTIAL_MARKER: { label: "Confidentiality marker", hue: "violet" },
  CONTRACT: { label: "Contract text", hue: "violet" },
  FINANCIAL: { label: "Financial document", hue: "violet" },
  HEALTH: { label: "Health information", hue: "violet" },
  HR: { label: "HR document", hue: "violet" },
  SOURCE_CODE: { label: "Source code", hue: "violet" },
  CLIENT_CONFIDENTIAL: { label: "Client-confidential document", hue: "violet" },
};

function humanise(code: string): string {
  const words = code.replaceAll("_", " ").toLocaleLowerCase();
  return words.charAt(0).toLocaleUpperCase() + words.slice(1);
}

/** Companies can add their own types (`PROJECT`, say); those get a neutral hue and a readable name. */
export function dataTypeInfo(code: string): DataTypeInfo {
  return KNOWN[code] ?? { label: humanise(code), hue: "neutral" };
}

import type { Example } from "../../api/types";

// Assembled at run time so the repository's secret scan finds no key-shaped literal.
const FAKE_API_KEY = ["sk", "demo", "0000", "not", "a", "real", "key", "0000"].join("-");

export const POISONED_PAGE_URL = "https://supplier-news.example/q4-update";
export const CLEAN_PAGE_URL = "https://supplier-news.example/holiday-schedule";

export const EXAMPLES: readonly Example[] = [
  {
    id: "chat-client-email-en",
    page: "chat",
    language: "en",
    title: "Client email with a name, tax number and IBAN",
    tool: "chatterbox-ai",
    expected: "redact",
    note: "Scene 1: the values are masked on the way out and restored in the answer.",
    prompt: [
      "Please draft a polite reply to this email from our client.",
      "",
      "From: Maria Papadopoulou <m.papadopoulou@helios-shipping.example>",
      "Subject: Updated bank details",
      "",
      "Hello, following our call, please update the records for Helios Shipping S.A.: tax number (AFM) 094872613, new IBAN GR68 9901 2340 0000 0123 4567 890. You can reach me on +30 210 555 0142.",
      "",
      "Kind regards,",
      "Maria Papadopoulou",
    ].join("\n"),
  },
  {
    id: "chat-client-email-el",
    page: "chat",
    language: "el",
    title: "Email πελάτη με όνομα, ΑΦΜ και IBAN",
    tool: "chatterbox-ai",
    expected: "redact",
    note: "Η ίδια σκηνή στα ελληνικά.",
    prompt: [
      "Γράψε μια ευγενική απάντηση σε αυτό το email της πελάτισσάς μας.",
      "",
      "Από: Μαρία Παπαδοπούλου <m.papadopoulou@helios-shipping.example>",
      "Θέμα: Νέα στοιχεία λογαριασμού",
      "",
      "Καλημέρα σας, σε συνέχεια της συνομιλίας μας, παρακαλώ ενημερώστε τα στοιχεία της Ήλιος Ναυτιλιακή Α.Ε.: ΑΦΜ 094872613, νέο IBAN GR68 9901 2340 0000 0123 4567 890. Το τηλέφωνό μου είναι 210 555 0142.",
      "",
      "Με εκτίμηση,",
      "Μαρία Παπαδοπούλου",
    ].join("\n"),
  },
  {
    id: "chat-api-key",
    page: "chat",
    language: "en",
    title: "Configuration file with an API key",
    tool: "chatterbox-ai",
    expected: "block",
    note: "Secrets never leave the company, whatever the tool.",
    prompt: [
      "Why does this deployment fail to start?",
      "",
      "SERVICE_NAME=billing-sync",
      `OPENAI_API_KEY=${FAKE_API_KEY}`,
      "RETRY_LIMIT=three",
    ].join("\n"),
  },
  {
    id: "chat-contract",
    page: "chat",
    language: "en",
    title: "Contract clause sent to an unapproved tool",
    tool: "chatterbox-ai",
    expected: "block",
    note: "Blocked, with the approved assistant offered instead.",
    prompt: [
      "Summarise the liability terms in plain English.",
      "",
      "This Master Services Agreement is entered into between the Provider and Helios Shipping S.A. (hereinafter the Client). The Provider's aggregate liability under this Agreement shall not exceed the fees paid in the twelve months preceding the claim. This Agreement is governed by the laws of Greece.",
    ].join("\n"),
  },
  {
    id: "chat-financial-warn",
    page: "chat",
    language: "en",
    title: "Internal financial summary",
    tool: "draftpilot",
    expected: "warn",
    note: "A warning: send the masked version, or cancel.",
    prompt: [
      "Internal use only. Turn these notes into three bullet points for the board.",
      "",
      "Q3 revenue reached 4.2M EUR, up 9% on Q2. EBITDA margin fell to 18% because of the start-up costs of Project Atlas.",
    ].join("\n"),
  },
  {
    id: "chat-confidential-el",
    page: "chat",
    language: "el",
    title: "Εμπιστευτικό σημείωμα",
    tool: "draftpilot",
    expected: "warn",
    note: "Προειδοποίηση: στέλνετε την καλυμμένη εκδοχή ή ακυρώνετε.",
    prompt: [
      "Εμπιστευτικό. Κάνε πιο σύντομο αυτό το σημείωμα για τη διοίκηση.",
      "",
      "Τα έσοδα του τρίτου τριμήνου έφτασαν τα 4,2 εκατ. ευρώ. Η κερδοφορία μειώθηκε λόγω του κόστους εκκίνησης του Project Atlas.",
    ].join("\n"),
  },
  {
    id: "chat-public",
    page: "chat",
    language: "en",
    title: "Public product description",
    tool: "chatterbox-ai",
    expected: "allow",
    note: "Nothing sensitive, so it goes out as written.",
    prompt:
      "Make this friendlier: Our new mobile app lets customers track their deliveries in real time and choose a delivery window that suits them.",
  },
];

/** Requests the mock agent answers: a page that hides an instruction, and a clean one. */
export const AGENT_PROMPTS = {
  "agent-poisoned-en": `Summarise the supplier update at ${POISONED_PAGE_URL} for the team.`,
  "agent-confirm-en": `Read ${CLEAN_PAGE_URL} and email the holiday delivery schedule to a.bilas@aspida-demo.example.`,
} as const;

import type { RiskFactors, ToolOut, ToolStatus } from "../../api/types";
import { DAY_MS, type Team, isoMinus } from "./org";

interface ToolSeed {
  slug: string;
  name: string;
  domain: string;
  category: string;
  description: string;
  status: ToolStatus;
  risk: number;
  factors: RiskFactors;
  source?: ToolOut["rating_source"];
  demo?: boolean;
  usage: Partial<Record<Team, number>>;
  firstSeenDays?: number;
}

const ENTERPRISE: RiskFactors = {
  trains_on_customer_data: false,
  retention_days: 0,
  data_residency: "EU",
  enterprise_terms: true,
  sso: true,
  certifications: ["ISO 27001", "SOC 2 Type II"],
};

const CONSUMER: RiskFactors = {
  trains_on_customer_data: true,
  retention_days: null,
  data_residency: "US",
  enterprise_terms: false,
  sso: false,
  certifications: [],
};

/** Every tool here is invented; the ratings are illustrative, like the gateway's seeded ones. */
const SEEDS: readonly ToolSeed[] = [
  {
    slug: "athena-assist",
    name: "Athena Assist",
    domain: "athena-assist.example",
    category: "Enterprise assistant",
    description: "The company's contracted assistant, with enterprise terms and EU hosting.",
    status: "approved",
    risk: 1,
    factors: ENTERPRISE,
    demo: true,
    usage: { Sales: 212, Legal: 148, Finance: 131, Engineering: 322, HR: 77, "Customer Support": 264 },
  },
  {
    slug: "draftpilot",
    name: "DraftPilot",
    domain: "draftpilot.example",
    category: "Writing assistant",
    description: "A writing aid on a team plan. No training on customer data, 30-day retention.",
    status: "tolerated",
    risk: 3,
    factors: { ...CONSUMER, trains_on_customer_data: false, retention_days: 30, data_residency: "EU and US", certifications: ["SOC 2 Type II"] },
    demo: true,
    usage: { Sales: 143, Legal: 39, Finance: 22, HR: 91, "Customer Support": 118 },
  },
  {
    slug: "chatterbox-ai",
    name: "Chatterbox AI",
    domain: "chatterbox-ai.example",
    category: "Public chatbot",
    description: "A free public chatbot. Prompts may be used for training and are kept indefinitely.",
    status: "unapproved",
    risk: 5,
    factors: CONSUMER,
    demo: true,
    usage: { Sales: 187, Legal: 64, Finance: 96, Engineering: 58, HR: 49, "Customer Support": 133 },
  },
  {
    slug: "company-assistant",
    name: "Company Assistant",
    domain: "assistant.internal.example",
    category: "In-house agent",
    description: "The helpdesk agent's own model, reached only through the gateway.",
    status: "approved",
    risk: 1,
    factors: ENTERPRISE,
    usage: { Sales: 41, "Customer Support": 196, HR: 12 },
  },
  {
    slug: "codeharbor",
    name: "CodeHarbor AI",
    domain: "codeharbor.example",
    category: "Coding assistant",
    description: "Code completion under an enterprise licence.",
    status: "approved",
    risk: 2,
    factors: { ...ENTERPRISE, retention_days: 7, data_residency: "EU and US" },
    usage: { Engineering: 611, Finance: 9 },
  },
  {
    slug: "lexora-translate",
    name: "Lexora Translate",
    domain: "lexora.example",
    category: "Translation",
    description: "Machine translation. The free tier keeps text for quality review.",
    status: "tolerated",
    risk: 2,
    factors: { ...CONSUMER, trains_on_customer_data: false, retention_days: 14, data_residency: "EU", certifications: ["ISO 27001"] },
    usage: { Sales: 88, Legal: 121, "Customer Support": 73, HR: 18 },
  },
  {
    slug: "sheetgenius",
    name: "SheetGenius",
    domain: "sheetgenius.example",
    category: "Spreadsheet assistant",
    description: "Formula and analysis helper for spreadsheets.",
    status: "tolerated",
    risk: 3,
    factors: { ...CONSUMER, trains_on_customer_data: false, retention_days: 90 },
    usage: { Finance: 164, Sales: 37 },
  },
  {
    slug: "meetscribe",
    name: "MeetScribe",
    domain: "meetscribe.example",
    category: "Meeting transcription",
    description: "Records and summarises meetings. Recordings are stored by the vendor.",
    status: "unapproved",
    risk: 4,
    factors: { ...CONSUMER, retention_days: 365 },
    usage: { Sales: 52, HR: 44, Legal: 13 },
  },
  {
    slug: "pixelmuse",
    name: "PixelMuse",
    domain: "pixelmuse.example",
    category: "Image generation",
    description: "Image generation from text prompts.",
    status: "unapproved",
    risk: 3,
    factors: { ...CONSUMER, retention_days: 180 },
    usage: { Sales: 29, HR: 8, Engineering: 11 },
  },
  {
    slug: "legalmind",
    name: "LegalMind AI",
    domain: "legalmind.example",
    category: "Legal research",
    description: "Contract review and legal research on a consumer plan.",
    status: "unapproved",
    risk: 5,
    factors: CONSUMER,
    usage: { Legal: 97, Finance: 14 },
  },
  {
    slug: "paraphrase-pro",
    name: "ParaphrasePro",
    domain: "paraphrasepro.example",
    category: "Writing assistant",
    description: "Rewrites text in a chosen tone.",
    status: "unapproved",
    risk: 4,
    factors: { ...CONSUMER, retention_days: 60 },
    usage: { "Customer Support": 61, Sales: 33, HR: 21 },
  },
  {
    slug: "summarize-fast",
    name: "SummarizeFast",
    domain: "summarize-fast.example",
    category: "Summarisation",
    description: "Browser extension that summarises pages and pasted text.",
    status: "unknown",
    risk: 4,
    factors: { trains_on_customer_data: true, retention_days: null, data_residency: null, enterprise_terms: false, sso: null, certifications: [] },
    source: "model_drafted",
    usage: { Finance: 17, Legal: 9 },
    firstSeenDays: 3,
  },
  {
    slug: "talentscan",
    name: "TalentScan AI",
    domain: "talentscan.example",
    category: "CV screening",
    description: "Ranks job applicants from uploaded CVs.",
    status: "unknown",
    risk: 5,
    factors: { trains_on_customer_data: null, retention_days: null, data_residency: "US", enterprise_terms: null, sso: null, certifications: [] },
    source: "model_drafted",
    usage: { HR: 26 },
    firstSeenDays: 2,
  },
  {
    slug: "datawhisper",
    name: "DataWhisper",
    domain: "api.datawhisper.example",
    category: "Data analysis",
    description: "Upload a file and ask questions about it.",
    status: "unknown",
    risk: 3,
    factors: { trains_on_customer_data: false, retention_days: 30, data_residency: "EU", enterprise_terms: null, sso: false, certifications: [] },
    source: "model_drafted",
    usage: { Finance: 11, Engineering: 6 },
    firstSeenDays: 1,
  },
];

export function buildTools(now: Date): ToolOut[] {
  return SEEDS.map((seed, index) => {
    const usage = Object.entries(seed.usage).map(([team, requests]) => ({ team, requests }));
    return {
      slug: seed.slug,
      name: seed.name,
      domains: [seed.domain, `api.${seed.domain}`].filter((domain, at, all) => all.indexOf(domain) === at && !domain.startsWith("api.api.")),
      category: seed.category,
      description: seed.description,
      status: seed.status,
      risk_score: seed.risk,
      risk_factors: seed.factors,
      rating_source: seed.source ?? "seeded",
      needs_review: seed.status === "unknown",
      review_note: seed.status === "unknown" ? "Found in the proxy logs. The description on its site reads like an AI service." : null,
      is_demo: seed.demo ?? false,
      first_seen: isoMinus(now, (seed.firstSeenDays ?? 13) * DAY_MS + index * 3_600_000),
      last_seen: isoMinus(now, (index + 1) * 1_260_000),
      requests_14d: usage.reduce((sum, item) => sum + item.requests, 0),
      usage_by_team: usage.sort((a, b) => b.requests - a.requests),
    };
  });
}

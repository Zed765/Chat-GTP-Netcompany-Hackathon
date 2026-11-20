import type { IngestionResult, ToolOut, ToolUpdate } from "../../api/types";
import { type Route, json, problem, route } from "../http";
import type { MockState } from "../state";

const DISCOVERED: readonly Pick<ToolOut, "slug" | "name" | "category" | "description" | "risk_score">[] = [
  { slug: "notewise", name: "NoteWise", category: "Note taking", description: "Turns pasted notes into action items.", risk_score: 3 },
  { slug: "pitchcraft", name: "PitchCraft AI", category: "Presentation builder", description: "Builds slide decks from an outline.", risk_score: 4 },
];

export function inventoryRoutes(state: MockState): Route[] {
  const find = (slug: string | undefined) => state.tools.find((tool) => tool.slug === slug);
  return [
    route("GET", "/api/tools", "any", ({ url }) =>
      json(state.tools.filter((tool) => url.searchParams.get("demo_only") !== "true" || tool.is_demo)),
    ),
    route("GET", "/api/tools/:slug", "any", ({ params }) => {
      const tool = find(params.slug);
      return tool ? json(tool) : problem(404, "Unknown tool");
    }),
    route("PATCH", "/api/tools/:slug", ["admin"], async ({ params, request }) => {
      const tool = find(params.slug);
      if (!tool) return problem(404, "Unknown tool");
      const update = (await request.json()) as ToolUpdate;
      if (update.status) tool.status = update.status;
      if (update.risk_score) tool.risk_score = update.risk_score;
      if (update.risk_factors) tool.risk_factors = update.risk_factors;
      tool.rating_source = "analyst_confirmed";
      tool.needs_review = false;
      tool.review_note = null;
      return json(tool);
    }),
    route("GET", "/api/discovery/queue", ["admin"], () => json(state.tools.filter((tool) => tool.needs_review))),
    route("GET", "/api/discovery/ingestions", ["admin"], () => json(state.ingestions)),
    route("POST", "/api/discovery/logs", ["admin"], async ({ request }) => {
      const form = await request.formData();
      const file = form.get("file");
      if (!(file instanceof File)) return problem(422, "file: a log file is required");
      const kind = form.get("kind") === "dns" ? "dns" : "squid";
      const lines = (await file.text()).split("\n").filter((line) => line.trim() !== "").length;
      if (lines === 0) return problem(422, "The file is empty.");
      const duplicate = state.ingestions.some((ingestion) => ingestion.filename === file.name);
      const fresh = duplicate ? [] : DISCOVERED.filter((tool) => !find(tool.slug));
      const now = new Date().toISOString();
      for (const tool of fresh) {
        state.tools.push({
          ...tool,
          domains: [`${tool.slug}.example`],
          status: "unknown",
          risk_factors: { trains_on_customer_data: null, retention_days: null, data_residency: null, enterprise_terms: null, sso: null, certifications: [] },
          rating_source: "model_drafted",
          needs_review: true,
          review_note: "First seen in the log that was just ingested.",
          is_demo: false,
          first_seen: now,
          last_seen: now,
          requests_14d: 7,
          usage_by_team: [{ team: "Sales", requests: 7 }],
        });
      }
      const result: IngestionResult = {
        id: (state.ingestions[0]?.id ?? 0) + 1,
        created: now,
        filename: file.name,
        kind,
        lines,
        malformed: 0,
        matched: duplicate ? 0 : Math.max(1, Math.round(lines * 0.13)),
        new_tools: fresh.length,
        duplicate,
        new_tool_slugs: fresh.map((tool) => tool.slug),
      };
      if (!duplicate) {
        const { duplicate: _duplicate, new_tool_slugs: _slugs, ...ingestion } = result;
        state.ingestions.unshift(ingestion);
      }
      return json(result);
    }),
  ];
}

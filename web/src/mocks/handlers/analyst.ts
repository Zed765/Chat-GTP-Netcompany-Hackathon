import type { AskResult, EventPage } from "../../api/types";
import { STORED_QUESTIONS } from "../fixtures/ask";
import { buildOverview } from "../fixtures/events";
import { type Route, json, problem, route } from "../http";
import type { MockState } from "../state";

export function analystRoutes(state: MockState): Route[] {
  return [
    route("GET", "/api/overview", ["admin"], ({ url }) => {
      const days = Number(url.searchParams.get("days") ?? 14);
      return json(buildOverview(state.events, state.tools, new Date(), days));
    }),

    route("GET", "/api/events", ["admin"], ({ url }) => {
      const query = url.searchParams;
      const matches = state.events.filter(
        (event) =>
          (!query.get("team") || event.team === query.get("team")) &&
          (!query.get("tool") || event.tool === query.get("tool")) &&
          (!query.get("action") || event.action === query.get("action")) &&
          (!query.get("channel") || event.channel === query.get("channel")) &&
          (!query.get("data_type") || (query.get("data_type") as string) in event.data_counts),
      );
      const offset = Number(query.get("offset") ?? 0);
      const page: EventPage = { total: matches.length, items: matches.slice(offset, offset + Number(query.get("limit") ?? 50)) };
      return json(page);
    }),

    route("GET", "/api/events/:id", ["admin"], ({ params }) => {
      const event = state.events.find((candidate) => candidate.id === Number(params.id));
      return event ? json(event) : problem(404, "Unknown event");
    }),

    route("GET", "/api/ask/suggestions", ["admin"], () => json(STORED_QUESTIONS.map(({ question }) => ({ question })))),

    route("POST", "/api/ask", ["admin"], async ({ request }) => {
      const { question } = (await request.json()) as { question: string };
      const stored = STORED_QUESTIONS.find((item) => item.question.toLowerCase() === question.trim().toLowerCase());
      if (!stored) {
        return problem(503, "This question needs the language model, and no API key is configured. Choose one of the suggested questions, which are answered from stored SQL.");
      }
      const result: AskResult = {
        ...stored.answer({ events: state.events, tools: state.tools, now: new Date() }),
        sql: stored.sql,
        truncated: false,
      };
      return json(result);
    }),
  ];
}

import type { IdentityOut, MyData, Notice, PrivacySettings } from "../../api/types";
import { USERS } from "../fixtures/org";
import { type Route, json, problem, route } from "../http";
import type { MockState } from "../state";

const NOTICE: Notice = {
  inspected: [
    "The text you send to AI tools through the company gateway, checked by software before it leaves",
    "Pages, emails and records the helpdesk agent reads while working for you",
    "Which AI tool each request goes to",
  ],
  kept: [
    "The time, your team and the AI tool",
    "Which kinds of sensitive data were found and how many, never the values themselves",
    "What the policy decided and which rule applied",
    "A masked snippet of at most 200 characters, if the company has switched snippets on",
    "A pseudonym instead of your name. An admin can look up who sent one event, and that look-up is not recorded",
  ],
  never_kept: ["The text of your prompts and of the answers", "The real names, numbers and secrets found in them", "Documents that were uploaded for fingerprinting"],
};

const EMPLOYEES = [
  ["s.makris", "Stavros Makris"],
  ["a.vlachou", "Anna Vlachou"],
  ["p.nikolaidis", "Petros Nikolaidis"],
  ["d.christou", "Despina Christou"],
] as const;

export function privacyRoutes(state: MockState): Route[] {
  return [
    route("GET", "/api/privacy/notice", "public", () => json(NOTICE)),
    route("GET", "/api/privacy/settings", ["admin"], () => json(state.settings)),
    route("PUT", "/api/privacy/settings", ["admin"], async ({ request: incoming }) => {
      const update = (await incoming.json()) as Pick<PrivacySettings, "retention_days"> & { store_snippets?: boolean };
      if (!Number.isInteger(update.retention_days) || update.retention_days < 1 || update.retention_days > 3650) {
        return problem(422, "retention_days: choose a whole number of days between 1 and 3650");
      }
      state.settings = {
        ...state.settings,
        retention_days: update.retention_days,
        store_snippets: update.store_snippets ?? true,
      };
      return json(state.settings);
    }),

    route("GET", "/api/privacy/my-data", "any", ({ user }) => {
      const events = state.events.filter((event) => state.eventOwners.get(event.id) === user.user_id);
      const data: MyData = {
        user_id: user.user_id,
        team: user.team,
        retention_days: state.settings.retention_days,
        event_count: events.length,
        events: events.slice(0, 50),
        conversations: [...state.conversations]
          .filter(([, conversation]) => conversation.owner === user.user_id)
          .map(([conversation_id, conversation]) => ({
            conversation_id,
            placeholders: [...conversation.placeholders.values()].map(({ placeholder, dataType }) => ({
              placeholder,
              data_type: dataType,
            })),
          })),
      };
      return json(data);
    }),

    route("GET", "/api/events/:id/identity", ["admin"], ({ params }) => {
      const eventId = Number(params.id);
      const event = state.events.find((candidate) => candidate.id === eventId);
      if (!event) return problem(404, "No such event");
      const owner = USERS.find((candidate) => candidate.user_id === state.eventOwners.get(eventId));
      const [user_id, display_name] = EMPLOYEES[eventId % EMPLOYEES.length] ?? EMPLOYEES[0];
      const identity: IdentityOut = {
        event_id: eventId,
        user_id: owner?.user_id ?? user_id,
        display_name: owner?.display_name ?? display_name,
        team: owner?.team ?? event.team ?? "Unknown",
      };
      return json(identity);
    }),
  ];
}

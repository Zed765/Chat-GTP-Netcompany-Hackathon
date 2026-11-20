import { type CSSProperties, useRef, useState } from "react";
import { gateway, unwrap } from "../api/client";
import type { Action, Heatmap } from "../api/types";
import { EventList } from "../features/events/EventList";
import "../features/events/monitor.css";
import { useResource } from "../hooks/useResource";
import { dataTypeInfo } from "../lib/dataTypes";
import { formatCompact, formatNumber, formatPercent } from "../lib/format";
import { ACTIONS, ACTION_ORDER } from "../lib/labels";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { PageHeader } from "../ui/PageHeader";
import { EmptyState, ResourceView } from "../ui/States";
import { TableWrap } from "../ui/TableWrap";
import { Pagination, Segmented } from "../ui/controls";

const RANGES = [
  { value: "7", label: "7 days" },
  { value: "14", label: "14 days" },
  { value: "30", label: "30 days" },
] as const;

const PAGE_SIZE = 10;

/**
 * What the list of events is narrowed to. A figure or a cell shows exactly the events it counts,
 * so choosing one replaces the filter; the menus on the list combine freely.
 */
interface Filter {
  action: Action | "";
  team: string;
  dataType: string;
}

const EVERYTHING: Filter = { action: "", team: "", dataType: "" };

interface OutcomesProps {
  inspected: number;
  sensitiveShare: number;
  days: string;
  counts: Record<Action, number>;
  selected: Action | "";
  onSelect: (action: Action | "") => void;
}

/** What the firewall did with every request: one bar, and a figure per outcome that also narrows the events to it. */
function Outcomes({ inspected, sensitiveShare, days, counts, selected, onSelect }: OutcomesProps) {
  const total = Math.max(1, ACTION_ORDER.reduce((sum, action) => sum + counts[action], 0));
  return (
    <section className="outcomes" aria-label="What the firewall did">
      <p className="outcomes-lede">
        <strong>{formatNumber(inspected)}</strong> {inspected === 1 ? "request" : "requests"} inspected in the last {days} days. <strong>{formatPercent(sensitiveShare)}</strong> carried sensitive data.
      </p>
      <div className="outcomes-bar" aria-hidden="true">
        {ACTION_ORDER.filter((action) => counts[action] > 0).map((action) => (
          <span key={action} data-hue={ACTIONS[action].hue} data-off={selected !== "" && selected !== action ? "" : undefined} style={{ flexGrow: counts[action] }} />
        ))}
      </div>
      <div className="outcomes-figures" role="group" aria-label="Show the events with one outcome">
        {ACTION_ORDER.map((action) => (
          <button key={action} type="button" className="outcome" data-hue={ACTIONS[action].hue} aria-pressed={selected === action} onClick={() => onSelect(selected === action ? "" : action)}>
            <span className="outcome-name">
              <span className="event-dot" />
              {ACTIONS[action].past}
            </span>
            <span className="outcome-count">{formatCompact(counts[action])}</span>
            <span className="outcome-share">{formatPercent(counts[action] / total)}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

interface TeamMatrixProps {
  heatmap: Heatmap;
  filter: Filter;
  onFilter: (next: Filter) => void;
}

/** How often each team's requests carried each kind of data. A team, a kind or a cell narrows the events to it. */
function TeamMatrix({ heatmap, filter, onFilter }: TeamMatrixProps) {
  const peak = Math.max(1, ...heatmap.cells.flat());
  const level = (value: number) => Math.min(5, 1 + Math.floor((value / peak) * 4.999));
  const sum = (cells: readonly number[]) => cells.reduce((total, value) => total + value, 0);
  // The team that sent the most comes first, so the table reads from the top.
  const rows = heatmap.teams.map((team, index) => ({ team, cells: heatmap.cells[index] ?? [] })).toSorted((a, b) => sum(b.cells) - sum(a.cells));
  const outside = (team: string, type: string) => (filter.team !== "" && filter.team !== team) || (filter.dataType !== "" && filter.dataType !== type);

  return (
    <TableWrap label="Sensitive data by team" className="matrix-wrap">
      <table className="matrix" style={{ "--columns": heatmap.data_types.length } as CSSProperties}>
        <caption className="sr-only">Number of events from each team that carried each kind of data</caption>
        <thead>
          <tr>
            <th scope="col">
              <span className="sr-only">Team</span>
            </th>
            {heatmap.data_types.map((type) => (
              <th key={type} scope="col">
                <button type="button" className="matrix-name" aria-pressed={filter.dataType === type} onClick={() => onFilter({ action: "", team: filter.team, dataType: filter.dataType === type ? "" : type })}>
                  {dataTypeInfo(type).label}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(({ team, cells }) => (
            <tr key={team}>
              <th scope="row">
                <button type="button" className="matrix-name" aria-pressed={filter.team === team} onClick={() => onFilter({ action: "", team: filter.team === team ? "" : team, dataType: filter.dataType })}>
                  {team}
                </button>
              </th>
              {heatmap.data_types.map((type, column) => {
                const value = cells[column] ?? 0;
                const picked = filter.team === team && filter.dataType === type;
                return (
                  <td key={type}>
                    {value === 0 ? (
                      <span className="matrix-cell" data-level="0">
                        <span className="sr-only">0</span>
                      </span>
                    ) : (
                      <button
                        type="button"
                        className="matrix-cell"
                        data-level={level(value)}
                        data-off={outside(team, type) ? "" : undefined}
                        aria-pressed={picked}
                        aria-label={`${team}, ${dataTypeInfo(type).label}: ${formatNumber(value)}`}
                        onClick={() => onFilter({ action: "", team: picked ? "" : team, dataType: picked ? "" : type })}
                      >
                        {formatNumber(value)}
                      </button>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </TableWrap>
  );
}

interface FilterMenuProps {
  label: string;
  /** The choice that narrows nothing, for example "All teams". */
  all: string;
  value: string;
  options: readonly { value: string; label: string }[];
  onChange: (value: string) => void;
}

function FilterMenu({ label, all, value, options, onChange }: FilterMenuProps) {
  return (
    <select className="filter" aria-label={label} data-set={value ? "" : undefined} value={value} onChange={(change) => onChange(change.target.value)}>
      <option value="">{all}</option>
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

/** The names on offer, with the one in use added if this period no longer has it. */
const withCurrent = (names: readonly string[], current: string) => (current && !names.includes(current) ? [...names, current] : names);

interface EventsProps {
  filter: Filter;
  offset: number;
  teams: readonly string[];
  dataTypes: readonly string[];
  toolNames: ReadonlyMap<string, string>;
  onFilter: (next: Filter) => void;
  onOffset: (offset: number) => void;
}

function Events({ filter, offset, teams, dataTypes, toolNames, onFilter, onOffset }: EventsProps) {
  const events = useResource(`events:${filter.action}:${filter.team}:${filter.dataType}:${offset}`, (signal) =>
    unwrap(
      gateway.GET("/api/events", {
        params: {
          query: {
            action: filter.action || undefined,
            team: filter.team || undefined,
            data_type: filter.dataType || undefined,
            offset,
            limit: PAGE_SIZE,
          },
        },
        signal,
      }),
    ),
  );
  const narrowed = filter.action !== "" || filter.team !== "" || filter.dataType !== "";

  return (
    <Card
      title="Events"
      actions={
        <>
          {narrowed && (
            <Button size="sm" variant="ghost" onClick={() => onFilter(EVERYTHING)}>
              Clear
            </Button>
          )}
          <FilterMenu
            label="Outcome"
            all="All outcomes"
            value={filter.action}
            options={ACTION_ORDER.map((action) => ({ value: action, label: ACTIONS[action].past }))}
            onChange={(action) => onFilter({ ...filter, action: action as Action | "" })}
          />
          <FilterMenu
            label="Team"
            all="All teams"
            value={filter.team}
            options={withCurrent(teams, filter.team).map((team) => ({ value: team, label: team }))}
            onChange={(team) => onFilter({ ...filter, team })}
          />
          <FilterMenu
            label="Data found"
            all="All data"
            value={filter.dataType}
            options={withCurrent(dataTypes, filter.dataType).map((type) => ({ value: type, label: dataTypeInfo(type).label }))}
            onChange={(dataType) => onFilter({ ...filter, dataType })}
          />
        </>
      }
    >
      <ResourceView resource={events} label="events" isEmpty={(page) => page.items.length === 0} empty={<p className="muted events-none">No events match.</p>}>
        {(page) => (
          <div className="stack stack-sm">
            <EventList events={page.items} toolNames={toolNames} />
            <Pagination offset={offset} limit={PAGE_SIZE} total={page.total} onChange={onOffset} />
          </div>
        )}
      </ResourceView>
    </Card>
  );
}

export default function OverviewPage() {
  const [days, setDays] = useState<(typeof RANGES)[number]["value"]>("14");
  const [filter, setFilter] = useState<Filter>(EVERYTHING);
  const [offset, setOffset] = useState(0);
  const eventsRef = useRef<HTMLDivElement>(null);
  const overview = useResource(`overview:${days}`, (signal) =>
    unwrap(
      gateway.GET("/api/overview", {
        params: { query: { days: Number(days) } },
        signal,
      }),
    ),
  );
  const tools = useResource("tools", (signal) => unwrap(gateway.GET("/api/tools", { signal })));
  const toolNames = new Map((tools.data ?? []).map((tool) => [tool.slug, tool.name]));

  // A new filter starts again from the first page.
  const narrow = (next: Filter) => {
    setFilter(next);
    setOffset(0);
  };
  // The table sits below the events, so a choice made in it brings them back into view.
  const narrowFromTable = (next: Filter) => {
    narrow(next);
    const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    eventsRef.current?.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "start" });
  };

  return (
    <div className="page">
      <PageHeader title="Monitor" actions={<Segmented legend="Period" hideLegend options={RANGES} value={days} onChange={setDays} />} />
      <ResourceView
        resource={overview}
        label="the overview"
        isEmpty={(data) => data.prompts_inspected === 0}
        empty={
          <EmptyState icon="chart" title="Nothing has been inspected yet">
            Send a message from the Chat page and it shows up here.
          </EmptyState>
        }
      >
        {(data) => {
          const counts = Object.fromEntries(ACTION_ORDER.map((action) => [action, data.actions.find((item) => item.action === action)?.count ?? 0])) as Record<Action, number>;
          return (
            <div className="stack stack-lg">
              <Outcomes
                inspected={data.prompts_inspected}
                sensitiveShare={data.sensitive_share}
                days={days}
                counts={counts}
                selected={filter.action}
                onSelect={(action) => narrow({ ...EVERYTHING, action })}
              />
              <div ref={eventsRef} className="events-anchor">
                <Events filter={filter} offset={offset} teams={data.heatmap.teams} dataTypes={data.heatmap.data_types} toolNames={toolNames} onFilter={narrow} onOffset={setOffset} />
              </div>
              {data.heatmap.teams.length > 0 && (
                <Card title="Sensitive data by team">
                  <TeamMatrix heatmap={data.heatmap} filter={filter} onFilter={narrowFromTable} />
                </Card>
              )}
            </div>
          );
        }}
      </ResourceView>
    </div>
  );
}

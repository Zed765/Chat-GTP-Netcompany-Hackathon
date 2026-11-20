import { gateway, unwrap } from "../api/client";
import type { ToolStatus } from "../api/types";
import { useAction } from "../hooks/useAction";
import { useResource } from "../hooks/useResource";
import { TOOL_STATUS } from "../lib/labels";
import { Notice } from "../ui/Notice";
import { Setting, SettingNote } from "../ui/Settings";
import { ErrorState } from "../ui/States";
import { Segmented } from "../ui/controls";

const STATUSES: readonly { value: ToolStatus; label: string }[] = (["approved", "tolerated", "unapproved"] as const).map((value) => ({ value, label: TOOL_STATUS[value].label }));

/** The status of each AI tool on the Chat page. A change applies to the next request. */
export function ToolSettings() {
  const tools = useResource("demo-tools", (signal) => unwrap(gateway.GET("/api/tools", { params: { query: { demo_only: true } }, signal })));
  const change = useAction(async (slug: string, status: ToolStatus) => {
    await unwrap(gateway.PATCH("/api/tools/{slug}", { params: { path: { slug } }, body: { status } }));
    tools.reload();
  });

  if (tools.status === "loading") return null;
  if (tools.status === "error") {
    return (
      <SettingNote>
        <ErrorState message={tools.error.message} onRetry={tools.reload} />
      </SettingNote>
    );
  }
  return (
    <>
      {tools.data.map((tool) => (
        <Setting
          key={tool.slug}
          label={
            <>
              <span className="status-dot" data-hue={TOOL_STATUS[tool.status].hue} />
              {tool.name}
            </>
          }
        >
          <Segmented legend={`Status of ${tool.name}`} hideLegend options={STATUSES} value={tool.status} onChange={(status) => void change.run(tool.slug, status)} disabled={change.pending} />
        </Setting>
      ))}
      {change.error && (
        <SettingNote>
          <Notice tone="danger" role="alert">
            {change.error.message}
          </Notice>
        </SettingNote>
      )}
    </>
  );
}

import { PageHeader } from "../ui/PageHeader";
import { SettingsGroup } from "../ui/Settings";
import { AgentToolSettings } from "./AgentToolsSection";
import { PolicySettings } from "./PolicySection";
import { ProtectedDataSettings } from "./ProtectedDataSection";
import { RetentionSetting } from "./RetentionSection";
import { ToolSettings } from "./ToolsSection";

/**
 * Everything an admin sets, on one page: how far the agent's own systems are trusted, what counts as
 * sensitive, what happens when it is found, and which AI tools are allowed. Small
 * settings change in their row; large ones open in place.
 */
export default function ConfigurePage() {
  return (
    <div className="page">
      <PageHeader title="Configure" />
      <SettingsGroup title="Agent tools" note="A trusted system is believed and may receive real values. An untrusted one is treated as suspect and receives placeholders.">
        <AgentToolSettings />
      </SettingsGroup>
      <SettingsGroup title="Protected data">
        <ProtectedDataSettings />
      </SettingsGroup>
      <SettingsGroup title="Policy">
        <PolicySettings />
        <RetentionSetting />
      </SettingsGroup>
      <SettingsGroup title="AI tools">
        <ToolSettings />
      </SettingsGroup>
    </div>
  );
}

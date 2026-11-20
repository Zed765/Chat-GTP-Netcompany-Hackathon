import type { components as Agent } from "./agent";
import type { components as Gateway } from "./gateway";

type G = Gateway["schemas"];
type A = Agent["schemas"];

export type Action = G["Action"];
export type Channel = G["Channel"];
export type Tier = G["Tier"];
export type Role = G["Role"];
export type Store = G["Store"];
export type RowSource = G["RowSource"];
export type ToolStatus = G["ToolStatus"];
export type InjectionProtection = G["InjectionProtection"];

export type Meta = G["Meta"];
export type Principal = G["Principal"];
export type Session = G["Session"];
export type Example = G["Example"];
export type Notice = G["Notice"];
export type MyData = G["MyData"];

export type ChatMessage = G["ChatMessage"];
export type ChatCompletionRequest = G["ChatCompletionRequest"];
export type ChatCompletionEnvelope = G["ChatCompletionEnvelope"];
export type PolicyErrorResponse = G["PolicyErrorResponse"];
export type Trace = G["Trace"];
export type TraceSummary = G["TraceSummary"];
export type SpanView = G["SpanView"];
export type Explanation = G["Explanation"];
export type FoundItem = G["FoundItem"];
export type ToolRef = G["ToolRef"];
export type UpstreamMessage = G["UpstreamMessage"];

export type ToolOut = G["ToolOut"];
export type ToolUpdate = G["ToolUpdate"];
export type RiskFactors = G["RiskFactors"];
export type IngestionOut = G["IngestionOut"];
export type IngestionResult = G["IngestionResult"];

export type ProtectedSummary = G["ProtectedSummary"];
export type StoreSummary = G["StoreSummary"];
export type GroupOut = G["GroupOut"];
export type TermOut = G["TermOut"];
export type TermPage = G["TermPage"];
export type DocumentOut = G["DocumentOut"];
export type DocumentUploadResult = G["DocumentUploadResult"];
export type PatternOut = G["PatternOut"];
export type PatternIn = G["PatternIn"];
export type ImportResult = G["ImportResult"];
export type TestResult = G["TestResult"];
export type TestFinding = G["TestFinding"];
export type RemoveDemoResult = G["RemoveDemoResult"];

export type PolicyOut = G["PolicyOut"];
export type PolicyVersionSummary = G["PolicyVersionSummary"];
export type ValidateResult = G["ValidateResult"];
export type ValidationIssue = G["ValidationIssue"];
export type DraftResult = G["DraftResult"];
export type ReplayResult = G["ReplayResult"];
export type ReplayBreakdown = G["ReplayBreakdown"];

export type Overview = G["Overview"];
export type Heatmap = G["Heatmap"];
export type TrendPoint = G["TrendPoint"];
export type EventOut = G["EventOut"];
export type EventPage = G["EventPage"];
export type AskResult = G["AskResult"];
export type ChartSpec = G["ChartSpec"];
export type Suggestion = G["Suggestion"];

export type PrivacySettings = G["PrivacySettings"];
export type IdentityOut = G["IdentityOut"];
export type InboxMessage = G["InboxMessage"];
export type AgentTrust = G["AgentTrustOut"];

export type AgentSession = A["AgentSession"];
export type AgentMessage = A["AgentMessage"];
export type ToolCallEvent = A["ToolCallEvent"];
export type ToolResultEvent = A["ToolResultEvent"];
export type ToolDecision = A["ToolDecision"];
export type InjectionVerdict = A["InjectionVerdict"];
export type TraceStep = ToolCallEvent | ToolResultEvent;
/** One `data:` line of the agent's event stream. */
export type AgentEvent = A["TextDelta"] | TraceStep | A["DoneEvent"] | A["ErrorEvent"];

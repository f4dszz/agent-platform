import { useMemo, useState } from "react";
import type {
  Agent,
  AgentEvent,
  ApprovalRequest,
  CollaborationRun,
  RunStep,
} from "../types";
import { useTheme, t } from "./ThemeContext";

interface RunTimelineProps {
  run: CollaborationRun | null;
  steps: RunStep[];
  events: AgentEvent[];
  approvals: ApprovalRequest[];
  agents: Agent[];
  onJumpToMessage: (messageId: string) => void;
  onApprove: (approvalId: string) => Promise<void>;
  onDeny: (approvalId: string) => Promise<void>;
}

function formatLabel(value: string): string {
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(" ");
}

function agentDisplayName(agentName: string | null, agents: Agent[]): string {
  if (!agentName) return "System";
  return agents.find((agent) => agent.name === agentName)?.display_name ?? agentName;
}

export default function RunTimeline({
  run,
  steps,
  events,
  approvals,
  agents,
  onJumpToMessage,
  onApprove,
  onDeny,
}: RunTimelineProps) {
  const { mode } = useTheme();
  const tk = t(mode);
  const [actingApprovalId, setActingApprovalId] = useState<string | null>(null);

  const visibleEvents = useMemo(() => events.slice(-6), [events]);

  if (!run) return null;

  return (
    <div className={`mx-4 mt-3 rounded-2xl border ${tk.borderLight} ${tk.bgSecondary}/80 backdrop-blur`}>
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-white/10 px-4 py-3">
        <div>
          <div className={`text-[11px] font-semibold uppercase tracking-[0.24em] ${tk.textMuted}`}>
            Collaboration Run
          </div>
          <div className={`mt-1 text-sm font-medium ${tk.text}`}>
            {formatLabel(run.mode)} · {run.status}
          </div>
          <div className={`mt-1 text-xs ${tk.textDim}`}>
            steps {run.step_count}/{run.max_steps} · reviews {run.review_round_count}/{run.max_review_rounds}
          </div>
        </div>
        <div className={`max-w-[28rem] text-xs ${tk.textSecondary}`}>
          {run.stop_reason ? `Stop reason: ${formatLabel(run.stop_reason)}` : "Run is active."}
        </div>
      </div>

      {approvals.filter((item) => item.status === "pending").length > 0 ? (
        <div className="border-b border-white/10 px-4 py-3 space-y-2">
          <div className={`text-[10px] font-semibold uppercase tracking-[0.2em] ${tk.textMuted}`}>
            Approval Needed
          </div>
          {approvals
            .filter((item) => item.status === "pending")
            .map((approval) => (
              <div key={approval.id} className={`rounded-xl border px-3 py-3 ${tk.bgTertiary}/50 ${tk.border}`}>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className={`text-xs font-medium ${tk.text}`}>
                      {agentDisplayName(approval.agent_name, agents)} requests {approval.requested_permission_mode}
                    </div>
                    <div className={`mt-1 text-xs ${tk.textSecondary}`}>{approval.reason}</div>
                    {approval.error_text ? (
                      <div className={`mt-1 text-[11px] ${tk.textDim}`}>{approval.error_text}</div>
                    ) : null}
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      disabled={actingApprovalId === approval.id}
                      onClick={async () => {
                        setActingApprovalId(approval.id);
                        try {
                          await onApprove(approval.id);
                        } finally {
                          setActingApprovalId(null);
                        }
                      }}
                      className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
                    >
                      Approve
                    </button>
                    <button
                      disabled={actingApprovalId === approval.id}
                      onClick={async () => {
                        setActingApprovalId(approval.id);
                        try {
                          await onDeny(approval.id);
                        } finally {
                          setActingApprovalId(null);
                        }
                      }}
                      className="rounded-lg border border-rose-500/30 bg-rose-600/15 px-3 py-1.5 text-xs font-medium text-rose-300 hover:bg-rose-600/25 disabled:opacity-50"
                    >
                      Deny
                    </button>
                  </div>
                </div>
              </div>
            ))}
        </div>
      ) : null}

      <div className="grid gap-0 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
        <div className="px-4 py-3">
          <div className={`mb-2 text-[10px] font-semibold uppercase tracking-[0.2em] ${tk.textMuted}`}>
            Steps
          </div>
          <div className="space-y-2">
            {steps.length === 0 ? (
              <div className={`text-xs ${tk.textDim}`}>No structured steps yet.</div>
            ) : (
              steps.map((step) => (
                <button
                  key={step.id}
                  onClick={() => step.source_message_id && onJumpToMessage(step.source_message_id)}
                  className={`w-full rounded-xl border px-3 py-2 text-left transition-colors ${tk.border} ${tk.bgTertiary}/40 hover:bg-white/5`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className={`text-xs font-medium ${tk.text}`}>
                      {step.title || formatLabel(step.step_type)}
                    </div>
                    <div className={`text-[11px] ${tk.textMuted}`}>{step.status}</div>
                  </div>
                  <div className={`mt-1 text-[11px] ${tk.textDim}`}>
                    {agentDisplayName(step.agent_name, agents)} · {new Date(step.created_at).toLocaleTimeString()}
                  </div>
                </button>
              ))
            )}
          </div>
        </div>

        <div className="border-t border-white/10 px-4 py-3 lg:border-l lg:border-t-0">
          <div className={`mb-2 text-[10px] font-semibold uppercase tracking-[0.2em] ${tk.textMuted}`}>
            Live Events
          </div>
          <div className="space-y-2">
            {visibleEvents.length === 0 ? (
              <div className={`text-xs ${tk.textDim}`}>No events yet.</div>
            ) : (
              visibleEvents.map((event) => (
                <div key={event.id} className={`rounded-xl border px-3 py-2 ${tk.border} ${tk.bgTertiary}/30`}>
                  <div className={`text-[11px] font-semibold ${tk.textSecondary}`}>
                    {formatLabel(event.event_type)}
                  </div>
                  <div className={`mt-1 text-xs ${tk.textDim}`}>
                    {agentDisplayName(event.agent_name, agents)} · {new Date(event.created_at).toLocaleTimeString()}
                  </div>
                  {event.content ? (
                    <div className={`mt-1 text-xs ${tk.text}`}>{event.content}</div>
                  ) : null}
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

import { useMemo, useState, useEffect, useCallback } from "react";
import type {
  Agent,
  AgentEvent,
  ApprovalRequest,
  CollaborationRun,
  RunStep,
} from "../types";
import { useTheme, t } from "./ThemeContext";

import { updateRunLimits } from "../services/api";

interface RunTimelineProps {
  runs: CollaborationRun[];
  steps: RunStep[];
  events: AgentEvent[];
  approvals: ApprovalRequest[];
  agents: Agent[];
  onJumpToMessage: (messageId: string) => void;
  onApprove: (approvalId: string) => Promise<void>;
  onDeny: (approvalId: string) => Promise<void>;
  onRunUpdated?: (run: CollaborationRun) => void;
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

const STATUS_COLORS: Record<string, string> = {
  running: "bg-sky-500",
  completed: "bg-emerald-500",
  stopped: "bg-amber-500",
  blocked: "bg-rose-500",
  failed: "bg-rose-600",
};

export default function RunTimeline({
  runs,
  steps,
  events,
  approvals,
  agents,
  onJumpToMessage,
  onApprove,
  onDeny,
  onRunUpdated,
}: RunTimelineProps) {
  const { mode } = useTheme();
  const tk = t(mode);
  const [actingApprovalId, setActingApprovalId] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);

  const adjustLimit = useCallback(
    async (runId: string, field: "max_steps" | "max_review_rounds", current: number, delta: number) => {
      const next = Math.max(1, current + delta);
      if (next === current) return;
      try {
        const updated = await updateRunLimits(runId, { [field]: next });
        onRunUpdated?.(updated);
      } catch (err) {
        console.error("Failed to update run limits:", err);
      }
    },
    [onRunUpdated]
  );

  const sortedRuns = useMemo(
    () =>
      [...runs].sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      ),
    [runs]
  );

  const run = useMemo(() => {
    if (selectedRunId) return sortedRuns.find((r) => r.id === selectedRunId) ?? null;
    return sortedRuns.find((r) => r.status === "running") ?? sortedRuns[0] ?? null;
  }, [sortedRuns, selectedRunId]);

  const runSteps = useMemo(
    () => (run ? steps.filter((s) => s.run_id === run.id) : []),
    [steps, run]
  );
  const runEvents = useMemo(
    () => (run ? events.filter((e) => e.run_id === run.id) : []),
    [events, run]
  );
  const visibleEvents = useMemo(() => runEvents.slice(-6), [runEvents]);
  const runApprovals = useMemo(
    () => (run ? approvals.filter((a) => a.run_id === run.id) : []),
    [approvals, run]
  );

  const hasPendingApproval = runApprovals.some((a) => a.status === "pending");

  // Auto-expand when there's a pending approval
  useEffect(() => {
    if (hasPendingApproval) setCollapsed(false);
  }, [hasPendingApproval]);

  if (sortedRuns.length === 0) return null;

  const currentIndex = run ? sortedRuns.findIndex((r) => r.id === run.id) : -1;
  const runLabel = sortedRuns.length > 1 ? ` #${sortedRuns.length - currentIndex}` : "";

  return (
    <div className={`mx-4 mt-3 rounded-2xl border ${tk.borderLight} ${tk.bgSecondary}/80 backdrop-blur`}>
      {/* Clickable header — always visible */}
      <button
        type="button"
        onClick={() => setCollapsed((prev) => !prev)}
        className="flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left"
      >
        <div className="flex items-center gap-2 min-w-0">
          {run && (
            <span className={`w-2 h-2 rounded-full flex-shrink-0 ${STATUS_COLORS[run.status] ?? "bg-gray-500"}`} />
          )}
          <span className={`text-[11px] font-semibold uppercase tracking-[0.2em] ${tk.textMuted}`}>
            Collaboration Run{runLabel}
          </span>
          {run && (
            <span className={`text-[11px] ${tk.textDim}`}>
              {formatLabel(run.mode)} · {run.status}
              {run.step_count > 0 && ` · ${run.step_count} steps`}
            </span>
          )}
          {hasPendingApproval && (
            <span className="flex-shrink-0 rounded-full bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-medium text-amber-400">
              Approval needed
            </span>
          )}
        </div>
        <span className={`text-[11px] ${tk.textMuted} flex-shrink-0 transition-transform ${collapsed ? "" : "rotate-180"}`}>
          ▲
        </span>
      </button>

      {/* Collapsible body */}
      {!collapsed && (
        <>
          {/* Run selector tabs */}
          {sortedRuns.length > 1 && (
            <div className={`flex items-center gap-1.5 overflow-x-auto border-t border-white/5 px-4 pt-2 pb-1`}>
              {sortedRuns.map((r, idx) => {
                const isSelected = run?.id === r.id;
                const dotColor = STATUS_COLORS[r.status] ?? "bg-gray-500";
                return (
                  <button
                    key={r.id}
                    onClick={() => setSelectedRunId(r.id)}
                    className={`flex-shrink-0 flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[11px] font-medium transition-colors ${
                      isSelected
                        ? `${tk.bgTertiary} ${tk.text} ring-1 ring-white/10`
                        : `${tk.textMuted} hover:${tk.textSecondary} hover:bg-white/5`
                    }`}
                  >
                    <span className={`w-1.5 h-1.5 rounded-full ${dotColor}`} />
                    Run #{sortedRuns.length - idx}
                  </button>
                );
              })}
            </div>
          )}

          {run && (
            <>
              {/* Run details */}
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/10 px-4 py-2.5">
                <div className="flex items-center gap-4">
                  <span className={`text-xs ${tk.textDim}`}>
                    steps {run.step_count}/
                  </span>
                  <span className="inline-flex items-center gap-0.5">
                    <button
                      onClick={(e) => { e.stopPropagation(); adjustLimit(run.id, "max_steps", run.max_steps, -1); }}
                      className={`w-4 h-4 rounded flex items-center justify-center text-[10px] ${tk.textMuted} hover:${tk.text} hover:bg-white/10`}
                    >-</button>
                    <span className={`text-xs font-medium ${tk.text} min-w-[1rem] text-center`}>{run.max_steps}</span>
                    <button
                      onClick={(e) => { e.stopPropagation(); adjustLimit(run.id, "max_steps", run.max_steps, 1); }}
                      className={`w-4 h-4 rounded flex items-center justify-center text-[10px] ${tk.textMuted} hover:${tk.text} hover:bg-white/10`}
                    >+</button>
                  </span>
                  <span className={`text-xs ${tk.textDim}`}>
                    reviews {run.review_round_count}/
                  </span>
                  <span className="inline-flex items-center gap-0.5">
                    <button
                      onClick={(e) => { e.stopPropagation(); adjustLimit(run.id, "max_review_rounds", run.max_review_rounds, -1); }}
                      className={`w-4 h-4 rounded flex items-center justify-center text-[10px] ${tk.textMuted} hover:${tk.text} hover:bg-white/10`}
                    >-</button>
                    <span className={`text-xs font-medium ${tk.text} min-w-[1rem] text-center`}>{run.max_review_rounds}</span>
                    <button
                      onClick={(e) => { e.stopPropagation(); adjustLimit(run.id, "max_review_rounds", run.max_review_rounds, 1); }}
                      className={`w-4 h-4 rounded flex items-center justify-center text-[10px] ${tk.textMuted} hover:${tk.text} hover:bg-white/10`}
                    >+</button>
                  </span>
                </div>
                <div className={`max-w-[28rem] text-xs ${tk.textSecondary}`}>
                  {run.stop_reason ? `Stop reason: ${formatLabel(run.stop_reason)}` : "Run is active."}
                </div>
              </div>

              {/* Pending approvals */}
              {hasPendingApproval && (
                <div className="border-t border-white/10 px-4 py-3 space-y-2">
                  <div className={`text-[10px] font-semibold uppercase tracking-[0.2em] ${tk.textMuted}`}>
                    Approval Needed
                  </div>
                  {runApprovals
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
              )}

              {/* Steps + Events grid */}
              <div className="grid gap-0 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
                <div className="border-t border-white/10 px-4 py-3">
                  <div className={`mb-2 text-[10px] font-semibold uppercase tracking-[0.2em] ${tk.textMuted}`}>
                    Steps
                  </div>
                  <div className="space-y-2">
                    {runSteps.length === 0 ? (
                      <div className={`text-xs ${tk.textDim}`}>No structured steps yet.</div>
                    ) : (
                      runSteps.map((step) => (
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
            </>
          )}
        </>
      )}
    </div>
  );
}

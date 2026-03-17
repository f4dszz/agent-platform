interface AgentStatusProps {
  statuses: Record<string, "idle" | "working" | "offline">;
}

function statusDot(status: string): string {
  switch (status) {
    case "working":
      return "bg-yellow-400 animate-pulse";
    case "idle":
      return "bg-green-400";
    default:
      return "bg-gray-500";
  }
}

function statusLabel(status: string): string {
  switch (status) {
    case "working":
      return "Working...";
    case "idle":
      return "Online";
    default:
      return "Offline";
  }
}

function agentIcon(name: string): string {
  if (name.includes("claude")) return "🤖";
  if (name.includes("codex")) return "⚡";
  return "🔧";
}

export default function AgentStatus({ statuses }: AgentStatusProps) {
  const agents = Object.entries(statuses);

  if (agents.length === 0) {
    return (
      <div className="text-xs text-gray-500 px-3 py-2">
        No agents registered
      </div>
    );
  }

  return (
    <div className="space-y-1 px-3 py-2">
      <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
        Agents
      </div>
      {agents.map(([name, status]) => (
        <div key={name} className="flex items-center gap-2 py-1">
          <span className="text-sm">{agentIcon(name)}</span>
          <span className="text-sm text-gray-300 flex-1">{name}</span>
          <span className={`w-2 h-2 rounded-full ${statusDot(status)}`} />
          <span className="text-xs text-gray-500">{statusLabel(status)}</span>
        </div>
      ))}
    </div>
  );
}

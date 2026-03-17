import { useState, useEffect } from "react";
import type { Agent } from "../types";
import { updateAgent } from "../services/api";
import { useTheme, t } from "./ThemeContext";

const PERMISSION_MODES = [
  { value: "acceptEdits", label: "Accept Edits", desc: "Allow file edits (recommended)" },
  { value: "plan", label: "Plan Only", desc: "Only plan, no actions" },
  { value: "bypassPermissions", label: "Bypass All", desc: "Skip all permission checks (dangerous)" },
  { value: "default", label: "Default", desc: "Require confirmation (non-interactive = reject)" },
];

const TOOL_OPTIONS = ["Read", "Write", "Edit", "Bash", "Glob", "Grep"];

interface AgentSettingsProps {
  agent: Agent;
  onUpdated: (agent: Agent) => void;
}

export default function AgentSettings({ agent, onUpdated }: AgentSettingsProps) {
  const { mode } = useTheme();
  const tk = t(mode);

  const [permissionMode, setPermissionMode] = useState(agent.permission_mode);
  const [selectedTools, setSelectedTools] = useState<Set<string>>(() => {
    if (!agent.allowed_tools) return new Set(TOOL_OPTIONS); // null = all
    return new Set(agent.allowed_tools.split(",").map((s) => s.trim()).filter(Boolean));
  });
  const [allTools, setAllTools] = useState(!agent.allowed_tools);
  const [systemPrompt, setSystemPrompt] = useState(agent.system_prompt ?? "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  // Reset when agent changes
  useEffect(() => {
    setPermissionMode(agent.permission_mode);
    const hasAll = !agent.allowed_tools;
    setAllTools(hasAll);
    setSelectedTools(
      hasAll
        ? new Set(TOOL_OPTIONS)
        : new Set(agent.allowed_tools!.split(",").map((s) => s.trim()).filter(Boolean))
    );
    setSystemPrompt(agent.system_prompt ?? "");
  }, [agent.name, agent.permission_mode, agent.allowed_tools, agent.system_prompt]);

  const toggleTool = (tool: string) => {
    setAllTools(false);
    setSelectedTools((prev) => {
      const next = new Set(prev);
      if (next.has(tool)) next.delete(tool);
      else next.add(tool);
      // If all selected again, treat as "all"
      if (next.size === TOOL_OPTIONS.length) setAllTools(true);
      return next;
    });
  };

  const toggleAllTools = () => {
    if (allTools) {
      setAllTools(false);
      setSelectedTools(new Set());
    } else {
      setAllTools(true);
      setSelectedTools(new Set(TOOL_OPTIONS));
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setSaved(false);
    try {
      const toolsValue = allTools ? null : [...selectedTools].join(",") || null;
      const updated = await updateAgent(agent.name, {
        permission_mode: permissionMode,
        allowed_tools: toolsValue,
        system_prompt: systemPrompt || null,
      });
      onUpdated(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      console.error("Failed to update agent:", e);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={`px-2 py-2 space-y-3 text-xs border-t ${tk.border} ${tk.bgTertiary}/30`}>
      {/* Permission Mode */}
      <div>
        <label className={`block text-[10px] font-semibold ${tk.textMuted} uppercase tracking-widest mb-1`}>
          Permission Mode
        </label>
        <select
          value={permissionMode}
          onChange={(e) => setPermissionMode(e.target.value)}
          className={`w-full ${tk.inputBg} ${tk.inputText} ${tk.inputBorder} border rounded-lg px-2 py-1.5 text-xs outline-none focus:border-blue-500/50`}
        >
          {PERMISSION_MODES.map((pm) => (
            <option key={pm.value} value={pm.value}>
              {pm.label} — {pm.desc}
            </option>
          ))}
        </select>
      </div>

      {/* Allowed Tools (Claude only) */}
      {agent.agent_type === "claude" && (
        <div>
          <label className={`block text-[10px] font-semibold ${tk.textMuted} uppercase tracking-widest mb-1`}>
            Allowed Tools
          </label>
          <div className="flex flex-wrap gap-1">
            <button
              onClick={toggleAllTools}
              className={`px-2 py-1 rounded-md text-[11px] transition-colors border ${
                allTools
                  ? "bg-blue-600/20 text-blue-400 border-blue-500/30"
                  : `${tk.bgTertiary} ${tk.textSecondary} border-transparent`
              }`}
            >
              All
            </button>
            {TOOL_OPTIONS.map((tool) => (
              <button
                key={tool}
                onClick={() => toggleTool(tool)}
                className={`px-2 py-1 rounded-md text-[11px] transition-colors border ${
                  selectedTools.has(tool)
                    ? "bg-blue-600/20 text-blue-400 border-blue-500/30"
                    : `${tk.bgTertiary} ${tk.textSecondary} border-transparent`
                }`}
              >
                {tool}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* System Prompt */}
      <div>
        <label className={`block text-[10px] font-semibold ${tk.textMuted} uppercase tracking-widest mb-1`}>
          System Prompt
        </label>
        <textarea
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
          rows={3}
          placeholder="e.g. 你是代码审核员，专注于代码质量..."
          className={`w-full ${tk.inputBg} ${tk.inputText} ${tk.inputBorder} ${tk.inputPlaceholder} border rounded-lg px-2 py-1.5 text-xs outline-none focus:border-blue-500/50 resize-none`}
        />
      </div>

      {/* Save */}
      <button
        onClick={handleSave}
        disabled={saving}
        className={`w-full py-1.5 rounded-lg text-xs font-medium transition-colors ${
          saved
            ? "bg-green-600/20 text-green-400 border border-green-500/30"
            : "bg-blue-600 text-white hover:bg-blue-500"
        } disabled:opacity-50`}
      >
        {saving ? "Saving..." : saved ? "Saved" : "Save"}
      </button>
    </div>
  );
}

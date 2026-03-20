import { useState, useEffect } from "react";
import type { Agent } from "../types";
import { toggleAgent, updateAgent } from "../services/api";
import { useTheme, t } from "./ThemeContext";

const PERMISSION_MODES = [
  { value: "acceptEdits", label: "Accept Edits", desc: "Allow execution without manual approval" },
  { value: "plan", label: "Plan Only", desc: "Read-only planning mode" },
  { value: "bypassPermissions", label: "Bypass All", desc: "Skip approvals and sandbox checks" },
  { value: "default", label: "Default", desc: "Provider default behavior" },
];

const TOOL_OPTIONS = ["Read", "Write", "Edit", "Bash", "Glob", "Grep"];
const MODEL_SUGGESTIONS: Record<Agent["agent_type"], string[]> = {
  claude: ["claude-sonnet-4.5", "claude-opus-4.1"],
  codex: ["gpt-5.4", "gpt-5.2", "gpt-5-codex"],
};

interface AgentSettingsProps {
  agent: Agent;
  onUpdated: (agent: Agent) => void;
}

export default function AgentSettings({ agent, onUpdated }: AgentSettingsProps) {
  const { mode } = useTheme();
  const tk = t(mode);

  const [displayName, setDisplayName] = useState(agent.display_name);
  const [command, setCommand] = useState(agent.command);
  const [model, setModel] = useState(agent.model ?? "");
  const [defaultArgs, setDefaultArgs] = useState(agent.default_args ?? "");
  const [maxTimeout, setMaxTimeout] = useState(String(agent.max_timeout));
  const [permissionMode, setPermissionMode] = useState(agent.permission_mode);
  const [selectedTools, setSelectedTools] = useState<Set<string>>(() => {
    if (!agent.allowed_tools) return new Set(TOOL_OPTIONS);
    return new Set(agent.allowed_tools.split(",").map((part) => part.trim()).filter(Boolean));
  });
  const [allTools, setAllTools] = useState(!agent.allowed_tools);
  const [avatarLabel, setAvatarLabel] = useState(agent.avatar_label ?? "");
  const [avatarColor, setAvatarColor] = useState(agent.avatar_color ?? "#2563eb");
  const [systemPrompt, setSystemPrompt] = useState(agent.system_prompt ?? "");
  const [saving, setSaving] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setDisplayName(agent.display_name);
    setCommand(agent.command);
    setModel(agent.model ?? "");
    setDefaultArgs(agent.default_args ?? "");
    setMaxTimeout(String(agent.max_timeout));
    setPermissionMode(agent.permission_mode);
    const hasAllTools = !agent.allowed_tools;
    setAllTools(hasAllTools);
    setSelectedTools(
      hasAllTools
        ? new Set(TOOL_OPTIONS)
        : new Set(agent.allowed_tools!.split(",").map((part) => part.trim()).filter(Boolean))
    );
    setAvatarLabel(agent.avatar_label ?? "");
    setAvatarColor(agent.avatar_color ?? "#2563eb");
    setSystemPrompt(agent.system_prompt ?? "");
  }, [
    agent.name,
    agent.display_name,
    agent.command,
    agent.model,
    agent.default_args,
    agent.max_timeout,
    agent.permission_mode,
    agent.allowed_tools,
    agent.avatar_label,
    agent.avatar_color,
    agent.system_prompt,
    agent.enabled,
  ]);

  const toggleTool = (tool: string) => {
    setAllTools(false);
    setSelectedTools((prev) => {
      const next = new Set(prev);
      if (next.has(tool)) next.delete(tool);
      else next.add(tool);
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

  const handleToggleEnabled = async () => {
    setToggling(true);
    try {
      const updated = await toggleAgent(agent.name);
      onUpdated(updated);
    } catch (error) {
      console.error("Failed to toggle agent:", error);
    } finally {
      setToggling(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setSaved(false);
    try {
      const parsedTimeout = Number(maxTimeout);
      const timeoutValue = Number.isFinite(parsedTimeout)
        ? Math.min(3600, Math.max(10, Math.round(parsedTimeout)))
        : agent.max_timeout;
      const toolsValue = allTools ? null : [...selectedTools].join(",") || null;
      const updated = await updateAgent(agent.name, {
        display_name: displayName.trim() || agent.display_name,
        command: command.trim() || agent.command,
        model: model.trim() || null,
        default_args: defaultArgs.trim() || null,
        max_timeout: timeoutValue,
        permission_mode: permissionMode,
        allowed_tools: toolsValue,
        avatar_label: avatarLabel.trim() || null,
        avatar_color: avatarColor.trim() || null,
        system_prompt: systemPrompt.trim() || null,
      });
      onUpdated(updated);
      setMaxTimeout(String(updated.max_timeout));
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (error) {
      console.error("Failed to update agent:", error);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={`px-2 py-2 space-y-3 text-xs border-t ${tk.border} ${tk.bgTertiary}/30`}>
      <div className="flex items-center justify-between gap-2">
        <div>
          <div className={`text-[10px] font-semibold ${tk.textMuted} uppercase tracking-widest`}>
            Runtime
          </div>
          <div className={`mt-1 text-xs ${tk.textSecondary}`}>
            {agent.enabled ? "Enabled" : "Disabled"}
          </div>
        </div>
        <button
          onClick={handleToggleEnabled}
          disabled={toggling}
          className={`rounded-lg px-3 py-1.5 text-[11px] font-medium transition-colors ${
            agent.enabled
              ? "bg-rose-600/15 text-rose-300 border border-rose-500/30"
              : "bg-emerald-600/15 text-emerald-300 border border-emerald-500/30"
          } disabled:opacity-50`}
        >
          {toggling ? "Updating..." : agent.enabled ? "Disable" : "Enable"}
        </button>
      </div>

      <div>
        <label className={`block text-[10px] font-semibold ${tk.textMuted} uppercase tracking-widest mb-1`}>
          Display Name
        </label>
        <input
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          className={`w-full ${tk.inputBg} ${tk.inputText} ${tk.inputBorder} border rounded-lg px-2 py-1.5 text-xs outline-none focus:border-blue-500/50`}
        />
      </div>

      <div>
        <label className={`block text-[10px] font-semibold ${tk.textMuted} uppercase tracking-widest mb-1`}>
          Command
        </label>
        <input
          value={command}
          onChange={(e) => setCommand(e.target.value)}
          placeholder="claude or codex"
          className={`w-full ${tk.inputBg} ${tk.inputText} ${tk.inputBorder} border rounded-lg px-2 py-1.5 text-xs outline-none focus:border-blue-500/50`}
        />
      </div>

      <div>
        <label className={`block text-[10px] font-semibold ${tk.textMuted} uppercase tracking-widest mb-1`}>
          Model
        </label>
        <input
          value={model}
          onChange={(e) => setModel(e.target.value)}
          list={`models-${agent.name}`}
          placeholder="Leave empty to use CLI default"
          className={`w-full ${tk.inputBg} ${tk.inputText} ${tk.inputBorder} ${tk.inputPlaceholder} border rounded-lg px-2 py-1.5 text-xs outline-none focus:border-blue-500/50`}
        />
        <datalist id={`models-${agent.name}`}>
          {MODEL_SUGGESTIONS[agent.agent_type].map((item) => (
            <option key={item} value={item} />
          ))}
        </datalist>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className={`block text-[10px] font-semibold ${tk.textMuted} uppercase tracking-widest mb-1`}>
            Timeout (s)
          </label>
          <input
            type="number"
            min={10}
            max={3600}
            value={maxTimeout}
            onChange={(e) => setMaxTimeout(e.target.value)}
            className={`w-full ${tk.inputBg} ${tk.inputText} ${tk.inputBorder} border rounded-lg px-2 py-1.5 text-xs outline-none focus:border-blue-500/50`}
          />
        </div>
        <div>
          <label className={`block text-[10px] font-semibold ${tk.textMuted} uppercase tracking-widest mb-1`}>
            Permission Mode
          </label>
          <select
            value={permissionMode}
            onChange={(e) => setPermissionMode(e.target.value)}
            className={`w-full ${tk.inputBg} ${tk.inputText} ${tk.inputBorder} border rounded-lg px-2 py-1.5 text-xs outline-none focus:border-blue-500/50`}
          >
            {PERMISSION_MODES.map((modeOption) => (
              <option key={modeOption.value} value={modeOption.value}>
                {modeOption.label} - {modeOption.desc}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label className={`block text-[10px] font-semibold ${tk.textMuted} uppercase tracking-widest mb-1`}>
          Default Args
        </label>
        <textarea
          value={defaultArgs}
          onChange={(e) => setDefaultArgs(e.target.value)}
          rows={2}
          placeholder='Examples: ["--model","gpt-5.2"] or --model gpt-5.2'
          className={`w-full ${tk.inputBg} ${tk.inputText} ${tk.inputBorder} ${tk.inputPlaceholder} border rounded-lg px-2 py-1.5 text-xs outline-none focus:border-blue-500/50 resize-none`}
        />
        <p className={`mt-1 text-[10px] ${tk.textDim}`}>
          Appended to the CLI command before the prompt.
        </p>
      </div>

      <div className="grid grid-cols-[1fr_auto] gap-2">
        <div>
          <label className={`block text-[10px] font-semibold ${tk.textMuted} uppercase tracking-widest mb-1`}>
            Avatar Label
          </label>
          <input
            value={avatarLabel}
            maxLength={4}
            onChange={(e) => setAvatarLabel(e.target.value)}
            placeholder="C, X, AI"
            className={`w-full ${tk.inputBg} ${tk.inputText} ${tk.inputBorder} ${tk.inputPlaceholder} border rounded-lg px-2 py-1.5 text-xs outline-none focus:border-blue-500/50`}
          />
        </div>
        <div>
          <label className={`block text-[10px] font-semibold ${tk.textMuted} uppercase tracking-widest mb-1`}>
            Avatar Color
          </label>
          <input
            type="color"
            value={avatarColor}
            onChange={(e) => setAvatarColor(e.target.value)}
            className="h-[32px] w-[46px] rounded-lg border border-white/10 bg-transparent p-1"
          />
        </div>
      </div>

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

      <div>
        <label className={`block text-[10px] font-semibold ${tk.textMuted} uppercase tracking-widest mb-1`}>
          Personality Prompt
        </label>
        <textarea
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
          rows={4}
          placeholder="Tone, expertise, review style, collaboration rules"
          className={`w-full ${tk.inputBg} ${tk.inputText} ${tk.inputBorder} ${tk.inputPlaceholder} border rounded-lg px-2 py-1.5 text-xs outline-none focus:border-blue-500/50 resize-none`}
        />
      </div>

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

import { useEffect, useMemo, useState } from "react";
import type { Agent, AgentCapabilities } from "../types";
import { getAgentCapabilities, toggleAgent, updateAgent } from "../services/api";
import { useTheme, t } from "./ThemeContext";

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
  const [reasoningEffort, setReasoningEffort] = useState(agent.reasoning_effort ?? "");
  const [defaultArgs, setDefaultArgs] = useState(agent.default_args ?? "");
  const [maxTimeout, setMaxTimeout] = useState(String(agent.max_timeout));
  const [permissionMode, setPermissionMode] = useState(agent.permission_mode);
  const [toolRules, setToolRules] = useState(agent.allowed_tools ?? "");
  const [avatarLabel, setAvatarLabel] = useState(agent.avatar_label ?? "");
  const [avatarColor, setAvatarColor] = useState(agent.avatar_color ?? "#2563eb");
  const [systemPrompt, setSystemPrompt] = useState(agent.system_prompt ?? "");
  const [saving, setSaving] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [saved, setSaved] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [capabilities, setCapabilities] = useState<AgentCapabilities | null>(null);
  const [capabilitiesError, setCapabilitiesError] = useState<string | null>(null);
  const [modelMenuOpen, setModelMenuOpen] = useState(false);

  useEffect(() => {
    setDisplayName(agent.display_name);
    setCommand(agent.command);
    setModel(agent.model ?? "");
    setReasoningEffort(agent.reasoning_effort ?? "");
    setDefaultArgs(agent.default_args ?? "");
    setMaxTimeout(String(agent.max_timeout));
    setPermissionMode(agent.permission_mode);
    setToolRules(agent.allowed_tools ?? "");
    setAvatarLabel(agent.avatar_label ?? "");
    setAvatarColor(agent.avatar_color ?? "#2563eb");
    setSystemPrompt(agent.system_prompt ?? "");
    setSaved(false);
    setModelMenuOpen(false);
  }, [
    agent.name,
    agent.display_name,
    agent.command,
    agent.model,
    agent.reasoning_effort,
    agent.default_args,
    agent.max_timeout,
    agent.permission_mode,
    agent.allowed_tools,
    agent.avatar_label,
    agent.avatar_color,
    agent.system_prompt,
  ]);

  useEffect(() => {
    let cancelled = false;
    setCapabilitiesError(null);
    getAgentCapabilities(agent.name)
      .then((next) => {
        if (!cancelled) {
          setCapabilities(next);
        }
      })
      .catch((error) => {
        console.error("Failed to load agent capabilities:", error);
        if (!cancelled) {
          setCapabilities(null);
          setCapabilitiesError("Could not load provider capabilities");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [agent.name]);

  const visibleModelOptions = useMemo(() => {
    if (!capabilities) return [];
    const query = model.trim().toLowerCase();
    if (!query) return capabilities.model_options;
    const filtered = capabilities.model_options.filter((option) => {
      const haystack = `${option.label} ${option.value} ${option.description ?? ""}`.toLowerCase();
      return haystack.includes(query);
    });
    return filtered.length > 0 ? filtered : capabilities.model_options;
  }, [capabilities, model]);

  const executionOptions = useMemo(() => {
    if (!capabilities) {
      return [
        {
          value: permissionMode,
          label: permissionMode,
          description: null,
        },
      ];
    }
    const options = [...capabilities.execution_options];
    if (!options.some((option) => option.value === permissionMode)) {
      options.unshift({
        value: permissionMode,
        label: `Current (${permissionMode})`,
        description: "Saved legacy mode. Pick a new mode to normalize it.",
      });
    }
    return options;
  }, [capabilities, permissionMode]);

  const reasoningOptions = useMemo(() => {
    if (!capabilities?.reasoning_supported) return [];
    return capabilities.reasoning_options;
  }, [capabilities]);

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
      const updated = await updateAgent(agent.name, {
        display_name: displayName.trim() || agent.display_name,
        command: command.trim() || agent.command,
        model: model.trim() || null,
        reasoning_effort: reasoningEffort.trim() || null,
        default_args: defaultArgs.trim() || null,
        max_timeout: timeoutValue,
        permission_mode: permissionMode,
        allowed_tools:
          capabilities?.tool_rules_supported === true ? toolRules.trim() || null : agent.allowed_tools,
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
          Model
        </label>
        <div
          className="relative"
          onBlur={() => window.setTimeout(() => setModelMenuOpen(false), 120)}
        >
          <div className="relative">
            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              onFocus={() => setModelMenuOpen(true)}
              placeholder={capabilities?.model_placeholder ?? "Leave empty to use CLI default"}
              className={`w-full ${tk.inputBg} ${tk.inputText} ${tk.inputBorder} ${tk.inputPlaceholder} border rounded-lg px-2 py-1.5 pr-9 text-xs outline-none focus:border-blue-500/50`}
            />
            <button
              type="button"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => setModelMenuOpen((current) => !current)}
              className={`absolute inset-y-0 right-0 flex items-center px-2 ${tk.textMuted}`}
            >
              v
            </button>
          </div>
          {modelMenuOpen && visibleModelOptions.length > 0 && (
            <div
              className={`absolute z-20 mt-1 w-full overflow-hidden rounded-xl border ${tk.popoverBorder} ${tk.popoverBg} shadow-xl`}
            >
              {visibleModelOptions.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onMouseDown={(event) => {
                    event.preventDefault();
                    setModel(option.value);
                    setModelMenuOpen(false);
                  }}
                  className={`block w-full px-3 py-2 text-left transition-colors ${tk.popoverHover}`}
                >
                  <div className={`text-xs font-medium ${tk.text}`}>{option.label}</div>
                  <div className={`text-[10px] ${tk.textDim}`}>{option.value}</div>
                  {option.description && (
                    <div className={`mt-0.5 text-[10px] ${tk.textSecondary}`}>{option.description}</div>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
        {capabilities?.model_help && (
          <p className={`mt-1 text-[10px] ${tk.textDim}`}>{capabilities.model_help}</p>
        )}
        {capabilitiesError && (
          <p className="mt-1 text-[10px] text-rose-400">{capabilitiesError}</p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className={`block text-[10px] font-semibold ${tk.textMuted} uppercase tracking-widest mb-1`}>
            {capabilities?.reasoning_label ?? "Reasoning"}
          </label>
          <select
            value={reasoningEffort}
            onChange={(e) => setReasoningEffort(e.target.value)}
            disabled={!capabilities?.reasoning_supported}
            className={`w-full ${tk.inputBg} ${tk.inputText} ${tk.inputBorder} border rounded-lg px-2 py-1.5 text-xs outline-none focus:border-blue-500/50 disabled:opacity-60`}
          >
            <option value="">Provider Default</option>
            {reasoningOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          {capabilities?.reasoning_help && (
            <p className={`mt-1 text-[10px] ${tk.textDim}`}>{capabilities.reasoning_help}</p>
          )}
        </div>

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
      </div>

      <div>
        <label className={`block text-[10px] font-semibold ${tk.textMuted} uppercase tracking-widest mb-1`}>
          {capabilities?.execution_label ?? "Execution"}
        </label>
        <select
          value={permissionMode}
          onChange={(e) => setPermissionMode(e.target.value)}
          className={`w-full ${tk.inputBg} ${tk.inputText} ${tk.inputBorder} border rounded-lg px-2 py-1.5 text-xs outline-none focus:border-blue-500/50`}
        >
          {executionOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        {capabilities?.execution_help && (
          <p className={`mt-1 text-[10px] ${tk.textDim}`}>{capabilities.execution_help}</p>
        )}
      </div>

      <button
        type="button"
        onClick={() => setAdvancedOpen((current) => !current)}
        className={`flex w-full items-center justify-between rounded-xl border px-3 py-2 text-left ${tk.border} ${tk.bgTertiary}/40`}
      >
        <div>
          <div className={`text-[10px] font-semibold ${tk.textMuted} uppercase tracking-widest`}>
            Advanced
          </div>
          <div className={`mt-1 text-[10px] ${tk.textSecondary}`}>
            Command, prompt, provider-native overrides, and avatar branding
          </div>
        </div>
        <span className={tk.textMuted}>{advancedOpen ? "-" : "+"}</span>
      </button>

      {advancedOpen && (
        <div className="space-y-3 rounded-xl border border-white/5 bg-black/5 p-3">
          <div>
            <label className={`block text-[10px] font-semibold ${tk.textMuted} uppercase tracking-widest mb-1`}>
              Personality Prompt
            </label>
            <textarea
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              rows={3}
              placeholder="Tone, expertise, review style, collaboration rules"
              className={`w-full ${tk.inputBg} ${tk.inputText} ${tk.inputBorder} ${tk.inputPlaceholder} border rounded-lg px-2 py-1.5 text-xs outline-none focus:border-blue-500/50 resize-none`}
            />
          </div>

          {capabilities?.tool_rules_supported && (
            <div>
              <label className={`block text-[10px] font-semibold ${tk.textMuted} uppercase tracking-widest mb-1`}>
                {capabilities.tool_rules_label ?? "Tool Rules"}
              </label>
              <input
                value={toolRules}
                onChange={(e) => setToolRules(e.target.value)}
                placeholder={capabilities.tool_rules_placeholder ?? ""}
                className={`w-full ${tk.inputBg} ${tk.inputText} ${tk.inputBorder} ${tk.inputPlaceholder} border rounded-lg px-2 py-1.5 text-xs outline-none focus:border-blue-500/50`}
              />
              {capabilities.tool_rules_help && (
                <p className={`mt-1 text-[10px] ${tk.textDim}`}>{capabilities.tool_rules_help}</p>
              )}
            </div>
          )}

          <div>
            <label className={`block text-[10px] font-semibold ${tk.textMuted} uppercase tracking-widest mb-1`}>
              Default Args
            </label>
            <textarea
              value={defaultArgs}
              onChange={(e) => setDefaultArgs(e.target.value)}
              rows={2}
              placeholder='Examples: ["--verbose"] or --verbose'
              className={`w-full ${tk.inputBg} ${tk.inputText} ${tk.inputBorder} ${tk.inputPlaceholder} border rounded-lg px-2 py-1.5 text-xs outline-none focus:border-blue-500/50 resize-none`}
            />
          </div>

          <div>
            <label className={`block text-[10px] font-semibold ${tk.textMuted} uppercase tracking-widest mb-1`}>
              Command
            </label>
            <input
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              placeholder={agent.agent_type === "claude" ? "claude" : "codex"}
              className={`w-full ${tk.inputBg} ${tk.inputText} ${tk.inputBorder} border rounded-lg px-2 py-1.5 text-xs outline-none focus:border-blue-500/50`}
            />
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
        </div>
      )}

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

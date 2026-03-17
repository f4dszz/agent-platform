import { useState, useRef, type KeyboardEvent } from "react";
import { useTheme, t } from "./ThemeContext";

interface MessageInputProps {
  onSend: (content: string) => void;
  disabled?: boolean;
  agentNames?: string[];
}

export default function MessageInput({
  onSend,
  disabled = false,
  agentNames = [],
}: MessageInputProps) {
  const { mode } = useTheme();
  const tk = t(mode);
  const [value, setValue] = useState("");
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const handleChange = (text: string) => {
    setValue(text);
    const match = text.match(/@(\w*)$/);
    if (match) {
      const partial = match[1].toLowerCase();
      const allMentions = ["all", ...agentNames];
      const filtered = allMentions.filter((name) =>
        name.toLowerCase().startsWith(partial)
      );
      setSuggestions(filtered);
      setShowSuggestions(filtered.length > 0);
      setSelectedIdx(0);
    } else {
      setShowSuggestions(false);
    }
  };

  const selectSuggestion = (name: string) => {
    const newValue = value.replace(/@(\w*)$/, `@${name} `);
    setValue(newValue);
    setShowSuggestions(false);
    setSelectedIdx(0);
    inputRef.current?.focus();
  };

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setValue("");
    setShowSuggestions(false);
    setSelectedIdx(0);
  };

  const handleKeyDown = (e: KeyboardEvent) => {
    if (showSuggestions && suggestions.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIdx((prev) => (prev + 1) % suggestions.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIdx((prev) =>
          prev <= 0 ? suggestions.length - 1 : prev - 1
        );
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        selectSuggestion(suggestions[selectedIdx]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setShowSuggestions(false);
        return;
      }
    }

    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className={`relative border-t ${tk.borderLight} p-3 ${tk.bgSecondary}/80 backdrop-blur`}>
      {/* @mention suggestions popup */}
      {showSuggestions && (
        <div
          className={`absolute bottom-full left-3 mb-2 ${tk.popoverBg} rounded-xl shadow-xl border ${tk.popoverBorder} py-1.5 z-10 min-w-[160px] overflow-hidden`}
        >
          {suggestions.map((name, idx) => (
            <button
              key={name}
              onClick={() => selectSuggestion(name)}
              onMouseEnter={() => setSelectedIdx(idx)}
              className={`block w-full text-left px-4 py-2 text-sm transition-colors ${
                idx === selectedIdx
                  ? mode === "dark"
                    ? "bg-blue-600/30 text-white"
                    : "bg-blue-100 text-blue-800"
                  : `${tk.text} ${tk.popoverHover}`
              }`}
            >
              <span className="text-blue-400 font-medium">@</span>
              {name}
              {idx === selectedIdx && (
                <span className={`float-right text-xs ${tk.textMuted}`}>
                  Enter
                </span>
              )}
            </button>
          ))}
        </div>
      )}

      <div className="flex items-end gap-2">
        <textarea
          ref={inputRef}
          value={value}
          onChange={(e) => handleChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder="Message...  use @claude  @codex  @all"
          rows={1}
          className={`flex-1 ${tk.inputBg} ${tk.inputText} rounded-xl px-4 py-2.5 text-sm resize-none outline-none border ${tk.inputBorder} focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/30 ${tk.inputPlaceholder} disabled:opacity-40 transition-all`}
        />
        <button
          onClick={handleSubmit}
          disabled={disabled || !value.trim()}
          className="bg-blue-600 hover:bg-blue-500 active:bg-blue-700 disabled:bg-gray-700 disabled:text-gray-500 disabled:cursor-not-allowed text-white rounded-xl px-4 py-2.5 text-sm font-medium transition-all shadow-sm hover:shadow-md"
        >
          Send
        </button>
      </div>
    </div>
  );
}

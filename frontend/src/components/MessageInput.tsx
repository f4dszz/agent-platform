import { useState, useRef, type KeyboardEvent } from "react";

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
  const [value, setValue] = useState("");
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
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
    } else {
      setShowSuggestions(false);
    }
  };

  const selectSuggestion = (name: string) => {
    const newValue = value.replace(/@(\w*)$/, `@${name} `);
    setValue(newValue);
    setShowSuggestions(false);
    inputRef.current?.focus();
  };

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setValue("");
    setShowSuggestions(false);
  };

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="relative border-t border-gray-700/50 p-3 bg-gray-800/80 backdrop-blur">
      {/* @mention suggestions */}
      {showSuggestions && (
        <div className="absolute bottom-full left-3 mb-2 bg-gray-800 rounded-xl shadow-xl border border-gray-600/50 py-1.5 z-10 min-w-[140px] overflow-hidden">
          {suggestions.map((name) => (
            <button
              key={name}
              onClick={() => selectSuggestion(name)}
              className="block w-full text-left px-4 py-2 text-sm text-gray-200 hover:bg-blue-600/30 hover:text-white transition-colors"
            >
              <span className="text-blue-400 font-medium">@</span>
              {name}
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
          className="flex-1 bg-gray-700/60 text-gray-100 rounded-xl px-4 py-2.5 text-sm resize-none outline-none border border-gray-600/30 focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/30 placeholder-gray-500 disabled:opacity-40 transition-all"
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

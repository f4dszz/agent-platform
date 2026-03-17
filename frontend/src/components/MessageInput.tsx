import { useState, useRef, type KeyboardEvent } from "react";

interface MessageInputProps {
  onSend: (content: string) => void;
  disabled?: boolean;
  /** Agent names available for @mention autocomplete */
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

    // Check if user is typing an @mention
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
    // Replace the partial @mention with the full one
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
    <div className="relative border-t border-gray-700 p-3 bg-gray-800">
      {/* @mention suggestions */}
      {showSuggestions && (
        <div className="absolute bottom-full left-3 mb-1 bg-gray-700 rounded-lg shadow-lg border border-gray-600 py-1 z-10">
          {suggestions.map((name) => (
            <button
              key={name}
              onClick={() => selectSuggestion(name)}
              className="block w-full text-left px-4 py-1.5 text-sm text-gray-200 hover:bg-gray-600 transition-colors"
            >
              @{name}
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
          placeholder="Type a message... (use @claude, @codex, or @all)"
          rows={1}
          className="flex-1 bg-gray-700 text-gray-200 rounded-lg px-4 py-2.5 text-sm resize-none outline-none focus:ring-2 focus:ring-blue-500 placeholder-gray-500 disabled:opacity-50"
        />
        <button
          onClick={handleSubmit}
          disabled={disabled || !value.trim()}
          className="bg-blue-600 hover:bg-blue-500 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg px-4 py-2.5 text-sm font-medium transition-colors"
        >
          Send
        </button>
      </div>
    </div>
  );
}

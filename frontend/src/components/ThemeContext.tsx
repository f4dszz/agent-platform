import { createContext, useContext, useState, useEffect, type ReactNode } from "react";

export type ThemeMode = "dark" | "light";
export type BubbleStyle = "modern" | "classic" | "minimal";

interface ThemeContextValue {
  mode: ThemeMode;
  bubbleStyle: BubbleStyle;
  setMode: (m: ThemeMode) => void;
  setBubbleStyle: (s: BubbleStyle) => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  mode: "dark",
  bubbleStyle: "modern",
  setMode: () => {},
  setBubbleStyle: () => {},
});

export function useTheme() {
  return useContext(ThemeContext);
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>(
    () => (localStorage.getItem("theme-mode") as ThemeMode) || "dark"
  );
  const [bubbleStyle, setBubbleStyle] = useState<BubbleStyle>(
    () => (localStorage.getItem("bubble-style") as BubbleStyle) || "modern"
  );

  useEffect(() => {
    localStorage.setItem("theme-mode", mode);
  }, [mode]);

  useEffect(() => {
    localStorage.setItem("bubble-style", bubbleStyle);
  }, [bubbleStyle]);

  return (
    <ThemeContext.Provider value={{ mode, bubbleStyle, setMode, setBubbleStyle }}>
      {children}
    </ThemeContext.Provider>
  );
}

// ── Theme tokens ──────────────────────────────────────────────────────────────

export function t(mode: ThemeMode) {
  const dark = mode === "dark";
  return {
    // Layout
    bg: dark ? "bg-gray-900" : "bg-gray-50",
    bgSecondary: dark ? "bg-gray-800" : "bg-white",
    bgTertiary: dark ? "bg-gray-700" : "bg-gray-100",
    border: dark ? "border-gray-800" : "border-gray-200",
    borderLight: dark ? "border-gray-700/50" : "border-gray-200/80",

    // Text
    text: dark ? "text-gray-100" : "text-gray-900",
    textSecondary: dark ? "text-gray-400" : "text-gray-500",
    textMuted: dark ? "text-gray-500" : "text-gray-400",
    textDim: dark ? "text-gray-600" : "text-gray-300",

    // Input
    inputBg: dark ? "bg-gray-700/60" : "bg-gray-100",
    inputBorder: dark ? "border-gray-600/30" : "border-gray-300",
    inputText: dark ? "text-gray-100" : "text-gray-900",
    inputPlaceholder: dark ? "placeholder-gray-500" : "placeholder-gray-400",

    // Sidebar
    sidebarBg: dark ? "bg-gray-900" : "bg-white",
    sidebarHover: dark ? "hover:bg-gray-800/70" : "hover:bg-gray-100",
    sidebarActive: dark
      ? "bg-blue-600/20 text-blue-300 border-blue-500/20"
      : "bg-blue-50 text-blue-700 border-blue-200",

    // Dropdown / popover
    popoverBg: dark ? "bg-gray-800" : "bg-white",
    popoverBorder: dark ? "border-gray-600/50" : "border-gray-200",
    popoverHover: dark ? "hover:bg-blue-600/30" : "hover:bg-blue-50",
  };
}

// ── Bubble styles ─────────────────────────────────────────────────────────────

export function bubbleClasses(
  senderType: string,
  style: BubbleStyle,
  mode: ThemeMode
): string {
  const dark = mode === "dark";

  if (style === "minimal") {
    return dark
      ? "bg-transparent border-l-2 border-gray-600 pl-3 rounded-none"
      : "bg-transparent border-l-2 border-gray-300 pl-3 rounded-none";
  }

  if (style === "classic") {
    // WhatsApp-style solid colored bubbles
    switch (senderType) {
      case "human":
        return dark
          ? "bg-blue-600 text-white rounded-2xl rounded-br-sm"
          : "bg-blue-500 text-white rounded-2xl rounded-br-sm";
      case "claude":
        return dark
          ? "bg-gray-700 rounded-2xl rounded-bl-sm"
          : "bg-white border border-gray-200 rounded-2xl rounded-bl-sm shadow-sm";
      case "codex":
        return dark
          ? "bg-gray-700 rounded-2xl rounded-bl-sm"
          : "bg-white border border-gray-200 rounded-2xl rounded-bl-sm shadow-sm";
      default:
        return dark ? "bg-gray-700/50 rounded-xl" : "bg-gray-100 rounded-xl";
    }
  }

  // "modern" (default) — translucent with colored border
  switch (senderType) {
    case "human":
      return dark
        ? "bg-blue-600/20 border border-blue-500/20 rounded-xl"
        : "bg-blue-50 border border-blue-200 rounded-xl";
    case "claude":
      return dark
        ? "bg-orange-600/10 border border-orange-500/20 rounded-xl"
        : "bg-orange-50 border border-orange-200 rounded-xl";
    case "codex":
      return dark
        ? "bg-emerald-600/10 border border-emerald-500/20 rounded-xl"
        : "bg-emerald-50 border border-emerald-200 rounded-xl";
    default:
      return dark
        ? "bg-gray-700/50 border border-gray-600/30 rounded-xl"
        : "bg-gray-100 border border-gray-200 rounded-xl";
  }
}

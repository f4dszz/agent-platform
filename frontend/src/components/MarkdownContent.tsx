import type { ComponentPropsWithoutRef } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { useTheme, t } from "./ThemeContext";

interface MarkdownContentProps {
  content: string;
}

type MarkdownCodeProps = ComponentPropsWithoutRef<"code"> & {
  inline?: boolean;
  node?: unknown;
};

export default function MarkdownContent({ content }: MarkdownContentProps) {
  const { mode } = useTheme();
  const tk = t(mode);
  const dark = mode === "dark";

  const components: Components = {
    p: ({ children }) => <p className="my-2 first:mt-0 last:mb-0">{children}</p>,
    ul: ({ children }) => (
      <ul className="my-2 list-disc space-y-1 pl-5 marker:text-gray-400">
        {children}
      </ul>
    ),
    ol: ({ children }) => (
      <ol className="my-2 list-decimal space-y-1 pl-5 marker:text-gray-400">
        {children}
      </ol>
    ),
    li: ({ children }) => <li className="pl-1">{children}</li>,
    blockquote: ({ children }) => (
      <blockquote
        className={`my-3 border-l-2 pl-4 italic ${
          dark ? "border-gray-500/70 text-gray-300" : "border-gray-300 text-gray-700"
        }`}
      >
        {children}
      </blockquote>
    ),
    hr: () => (
      <hr className={`my-4 border-0 border-t ${dark ? "border-gray-600/60" : "border-gray-300"}`} />
    ),
    strong: ({ children }) => (
      <strong className={`font-semibold ${dark ? "text-white" : "text-gray-950"}`}>
        {children}
      </strong>
    ),
    a: ({ href, children }) => (
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        className={dark ? "text-sky-300 underline underline-offset-2" : "text-sky-700 underline underline-offset-2"}
      >
        {children}
      </a>
    ),
    pre: ({ children }) => (
      <pre
        className={`my-3 overflow-x-auto rounded-lg border px-3 py-3 text-[13px] leading-6 ${
          dark
            ? "border-gray-700 bg-gray-950/80 text-gray-100"
            : "border-gray-300 bg-gray-950 text-gray-100"
        }`}
      >
        {children}
      </pre>
    ),
    code: ({ inline, className, children, ...props }: MarkdownCodeProps) => {
      const text = String(children ?? "");
      const isBlock = !inline && ((className ?? "").includes("language-") || text.includes("\n"));

      if (isBlock) {
        return (
          <code className="font-mono text-[13px] leading-6" {...props}>
            {children}
          </code>
        );
      }

      return (
        <code
          className={`rounded px-1.5 py-0.5 font-mono text-[0.85em] ${
            dark ? "bg-gray-800 text-amber-200" : "bg-gray-200 text-rose-700"
          }`}
          {...props}
        >
          {children}
        </code>
      );
    },
    table: ({ children }) => (
      <div className="my-3 overflow-x-auto">
        <table
          className={`min-w-full border-collapse text-left text-sm ${
            dark ? "border-gray-700" : "border-gray-300"
          }`}
        >
          {children}
        </table>
      </div>
    ),
    thead: ({ children }) => (
      <thead className={dark ? "bg-gray-800/80" : "bg-gray-200/70"}>{children}</thead>
    ),
    th: ({ children }) => (
      <th
        className={`border px-3 py-2 font-semibold ${
          dark ? "border-gray-700 text-gray-100" : "border-gray-300 text-gray-900"
        }`}
      >
        {children}
      </th>
    ),
    td: ({ children }) => (
      <td
        className={`border px-3 py-2 align-top ${
          dark ? "border-gray-700 text-gray-200" : "border-gray-300 text-gray-800"
        }`}
      >
        {children}
      </td>
    ),
  };

  return (
    <div className={`${tk.text} text-sm break-words leading-7`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}

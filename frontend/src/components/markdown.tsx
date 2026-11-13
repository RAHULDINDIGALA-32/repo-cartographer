"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function Markdown({ text, citations = [] }: { text: string; citations?: number[] }) {
  const marker = (value: string) =>
    value.replace(/\[(\d+)\]/g, (_, index: string) =>
      citations.includes(Number(index)) ? `⟦${index}⟧` : `[${index}]`,
    );
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        text: ({ children }) => (
          <>
            {marker(String(children))
              .split(/(⟦\d+⟧)/)
              .map((part, index) =>
                part.startsWith("⟦") ? (
                  <button
                    className="citation-chip"
                    key={index}
                    type="button"
                    title={`Source ${part.slice(1, -1)}`}
                    onClick={() =>
                      document
                        .getElementById(`source-${part.slice(1, -1)}`)
                        ?.scrollIntoView({ behavior: "smooth", block: "center" })
                    }
                  >
                    {part.slice(1, -1)}
                  </button>
                ) : (
                  part
                ),
              )}
          </>
        ),
        code: ({ children, className }) => <code className={className}>{children}</code>,
      }}
    >
      {text || ""}
    </ReactMarkdown>
  );
}

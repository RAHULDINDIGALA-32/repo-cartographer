"use client";

import { ArrowUp, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { MAX_QUESTION_CHARS } from "@/api/config";

export function Composer({
  disabled,
  active,
  onAsk,
  onStop,
  initialValue = "",
}: {
  disabled: boolean;
  active: boolean;
  onAsk: (question: string) => void;
  onStop: () => void;
  initialValue?: string;
}) {
  const [value, setValue] = useState(initialValue);
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (!active) ref.current?.focus();
  }, [active]);
  const resize = () => {
    const element = ref.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 190)}px`;
  };
  const submit = () => {
    const question = value.trim();
    if (!question || disabled || active) return;
    setValue("");
    if (ref.current) ref.current.style.height = "auto";
    onAsk(question);
  };
  return (
    <div className="composer" aria-label="Ask a question">
      <textarea
        ref={ref}
        rows={1}
        maxLength={MAX_QUESTION_CHARS}
        value={value}
        disabled={disabled && !active}
        placeholder={disabled ? "Sever is waking up" : "Ask about this codebase"}
        onChange={(event) => {
          setValue(event.target.value);
          resize();
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit();
          }
        }}
      />
      <div className="composer-actions">
        <span className="counter">
          {value.length}/{MAX_QUESTION_CHARS}
        </span>
        {active ? (
          <button className="send stop" type="button" aria-label="Stop answer" onClick={onStop}>
            <Square size={15} fill="currentColor" aria-hidden /> Stop
          </button>
        ) : (
          <button
            className="send"
            type="button"
            aria-label="Send question"
            disabled={disabled || !value.trim()}
            onClick={submit}
          >
            <ArrowUp size={16} aria-hidden />
          </button>
        )}
      </div>
    </div>
  );
}

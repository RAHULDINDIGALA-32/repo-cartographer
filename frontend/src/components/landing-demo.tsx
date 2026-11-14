"use client";

import { useEffect, useRef, useState } from "react";
import { demoAnswer } from "@/content/landing";

export function LandingDemo() {
  const [playing, setPlaying] = useState(false);
  const [visible, setVisible] = useState(0);
  const cardRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = cardRef.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) setPlaying(true);
      },
      { threshold: 0.25 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!playing) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setVisible(demoAnswer.answer.length);
      return;
    }
    if (visible >= demoAnswer.answer.length) return;
    const timer = window.setTimeout(
      () => setVisible((value) => Math.min(value + 4, demoAnswer.answer.length)),
      18,
    );
    return () => window.clearTimeout(timer);
  }, [playing, visible]);

  const replay = () => {
    setVisible(0);
    setPlaying(true);
  };

  return (
    <div className="landing-demo" ref={cardRef}>
      <div className="demo-head">
        <span className="demo-kicker">Live answer replay</span>
        <span className="demo-repo">{demoAnswer.repo}</span>
      </div>
      <p className="demo-question">{demoAnswer.question}</p>
      <div className="demo-answer" aria-hidden="true">
        {demoAnswer.answer.slice(0, visible)}
        {visible < demoAnswer.answer.length && <span className="demo-caret" />}
      </div>
      <p className="sr-only">{demoAnswer.answer}</p>
      {visible >= demoAnswer.answer.length && (
        <div className="demo-sources" aria-label="Demo sources">
          {demoAnswer.sources.map((source) => (
            <a
              key={source.path}
              href={`https://github.com/pallets/flask/blob/main/${source.path}`}
              target="_blank"
              rel="noreferrer"
            >
              <span>{source.label}</span>
              <code>
                {source.path}:{source.lines}
              </code>
            </a>
          ))}
        </div>
      )}
      <button className="text-button demo-control" type="button" onClick={replay}>
        {visible >= demoAnswer.answer.length
          ? "Replay answer"
          : playing
            ? "Playing…"
            : "Play replay"}
      </button>
    </div>
  );
}

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { demoAnswer } from "@/content/landing";

const START_DELAY_MS = 700;
const REPLAY_PAUSE_MS = 6000;
const TYPE_INTERVAL_MS = 38;
const CHARS_PER_TICK = 3;

export function LandingDemo() {
  const [playing, setPlaying] = useState(false);
  const [paused, setPaused] = useState(false);
  const [visible, setVisible] = useState(0);
  const cardRef = useRef<HTMLDivElement>(null);
  const userPausedRef = useRef(false);
  const complete = visible >= demoAnswer.answer.length;

  const start = useCallback(() => {
    setPlaying(true);
    setPaused(false);
  }, []);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setVisible(demoAnswer.answer.length);
      setPlaying(false);
      return;
    }
    const timer = window.setTimeout(start, START_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [start]);

  useEffect(() => {
    const node = cardRef.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting && !userPausedRef.current) start();
      },
      { threshold: 0.2 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [start]);

  useEffect(() => {
    if (!playing || paused) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setVisible(demoAnswer.answer.length);
      return;
    }
    if (visible >= demoAnswer.answer.length) return;
    const timer = window.setTimeout(
      () => setVisible((value) => Math.min(value + CHARS_PER_TICK, demoAnswer.answer.length)),
      TYPE_INTERVAL_MS,
    );
    return () => window.clearTimeout(timer);
  }, [playing, paused, visible]);

  useEffect(() => {
    if (!complete || paused || userPausedRef.current) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const timer = window.setTimeout(() => {
      setVisible(0);
      setPlaying(true);
    }, REPLAY_PAUSE_MS);
    return () => window.clearTimeout(timer);
  }, [complete, paused]);

  const replay = () => {
    userPausedRef.current = false;
    setVisible(0);
    setPaused(false);
    setPlaying(true);
  };

  const togglePause = () => {
    if (complete) {
      replay();
      return;
    }
    if (!playing) {
      userPausedRef.current = false;
      start();
      return;
    }
    setPaused((value) => {
      const next = !value;
      userPausedRef.current = next;
      return next;
    });
  };

  return (
    <div className="landing-demo" ref={cardRef}>
      <div className="demo-chrome" aria-hidden>
        <span />
        <span />
        <span />
      </div>
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
      {complete && (
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
      <div className="demo-controls">
        <button className="text-button demo-control" type="button" onClick={togglePause}>
          {complete ? "Replay answer" : paused ? "Resume" : playing ? "Pause" : "Play replay"}
        </button>
      </div>
    </div>
  );
}

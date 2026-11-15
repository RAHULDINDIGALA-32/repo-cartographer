"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { formatMetricValue, landingContent, metricValues } from "@/content/landing";

const CYCLE_MS = 2600;

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function countUp(el: HTMLElement, metric: (typeof metricValues)[number]) {
  if (prefersReducedMotion()) {
    el.textContent = formatMetricValue(metric);
    return;
  }
  const duration = 980;
  const start = performance.now();
  const tick = (now: number) => {
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - (1 - t) ** 3;
    el.textContent = formatMetricValue(metric, metric.count * eased);
    if (t < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

export function LandingMetrics() {
  const sectionRef = useRef<HTMLElement>(null);
  const [active, setActive] = useState(false);
  const [focus, setFocus] = useState(0);
  const [pinned, setPinned] = useState(false);
  const runRef = useRef(0);

  const replay = useCallback(() => {
    runRef.current += 1;
    const run = runRef.current;
    const nodes = sectionRef.current?.querySelectorAll<HTMLElement>(".metric-value") ?? [];
    nodes.forEach((node, index) => {
      const metric = metricValues[index];
      if (!metric || run !== runRef.current) return;
      countUp(node, metric);
    });
  }, []);

  const activate = useCallback(() => {
    setActive(true);
    replay();
  }, [replay]);

  useEffect(() => {
    const node = sectionRef.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) activate();
        else {
          setActive(false);
          setPinned(false);
        }
      },
      { threshold: 0.35 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [activate]);

  useEffect(() => {
    const onHash = () => {
      if (window.location.hash === "#numbers") activate();
    };
    window.addEventListener("hashchange", onHash);
    onHash();
    return () => window.removeEventListener("hashchange", onHash);
  }, [activate]);

  useEffect(() => {
    if (!active || pinned || prefersReducedMotion()) return;
    const timer = window.setInterval(
      () => setFocus((value) => (value + 1) % landingContent.numbers.length),
      CYCLE_MS,
    );
    return () => window.clearInterval(timer);
  }, [active, pinned]);

  return (
    <section
      className={`landing-section landing-metrics${active ? " is-active" : ""}`}
      id="numbers"
      ref={sectionRef}
    >
      <div className="landing-container">
        <div className="section-intro">
          <p className="eyebrow">Measured, not guessed</p>
          <h2>Evidence for the trade-offs.</h2>
        </div>
        <div className="number-grid">
          {landingContent.numbers.map(([value, caption], index) => {
            const metric = metricValues[index];
            if (!metric) return null;
            const selected = focus === index;
            return (
              <article
                className={selected && active ? "is-focused" : undefined}
                key={value}
              >
                <button
                  className="metric-hit"
                  type="button"
                  onClick={() => {
                    setPinned(true);
                    setFocus(index);
                    const el = sectionRef.current?.querySelectorAll<HTMLElement>(".metric-value")[index];
                    if (el) countUp(el, metric);
                  }}
                >
                  <strong className="metric-value" aria-label={formatMetricValue(metric)}>
                    {formatMetricValue(metric)}
                  </strong>
                  <p>{caption}</p>
                </button>
              </article>
            );
          })}
        </div>
        <p className="section-caption">
          Recorded measurements from the project’s Flask and incremental-sync runs; values are not
          production guarantees. Click a row to hold it.
        </p>
      </div>
    </section>
  );
}

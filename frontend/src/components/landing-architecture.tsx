"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { landingContent } from "@/content/landing";

type NodeId =
  | (typeof landingContent.architecture.index)[number]["id"]
  | (typeof landingContent.architecture.ask)[number]["id"]
  | "postgres"
  | "gateway";

const CYCLE: NodeId[] = [
  "github",
  "jobs",
  "ingest",
  "writer",
  "postgres",
  "ui",
  "analyze",
  "retrieve",
  "generate",
  "gateway",
];

export function LandingArchitecture() {
  const boardRef = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState<NodeId>("github");
  const [pinned, setPinned] = useState(false);
  const [inView, setInView] = useState(false);
  const { architecture } = landingContent;
  const nodes = [...architecture.index, ...architecture.ask, architecture.spine, architecture.bus];
  const current = nodes.find((node) => node.id === active) ?? architecture.spine;

  const select = useCallback((id: NodeId, pin = false) => {
    setActive(id);
    if (pin) setPinned(true);
  }, []);

  useEffect(() => {
    const node = boardRef.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      ([entry]) => setInView(Boolean(entry?.isIntersecting)),
      { threshold: 0.28 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!inView || pinned || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const timer = window.setInterval(() => {
      setActive((value) => {
        const index = CYCLE.indexOf(value);
        const next = CYCLE[(index + 1 + CYCLE.length) % CYCLE.length];
        return next ?? "github";
      });
    }, 2200);
    return () => window.clearInterval(timer);
  }, [inView, pinned]);

  useEffect(() => {
    let disposed = false;
    let cleanup = () => {};
    const start = async () => {
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
      const [{ gsap }, { ScrollTrigger }] = await Promise.all([
        import("gsap"),
        import("gsap/ScrollTrigger"),
      ]);
      if (disposed || !boardRef.current) return;
      gsap.registerPlugin(ScrollTrigger);
      const context = gsap.context(() => {
        gsap.fromTo(
          ".arch-trace-line",
          { strokeDashoffset: 1 },
          {
            strokeDashoffset: 0,
            duration: 1.4,
            stagger: 0.12,
            ease: "power2.out",
            scrollTrigger: { trigger: boardRef.current, start: "top 78%", once: true },
          },
        );
        gsap.fromTo(
          ".arch-node",
          { y: 10, opacity: 0.7 },
          {
            y: 0,
            opacity: 1,
            duration: 0.45,
            stagger: 0.05,
            ease: "power2.out",
            scrollTrigger: { trigger: boardRef.current, start: "top 78%", once: true },
          },
        );
      }, boardRef);
      cleanup = () => context.revert();
    };
    void start();
    return () => {
      disposed = true;
      cleanup();
    };
  }, []);

  return (
    <section className="landing-section landing-architecture" id="architecture">
      <div className="landing-container">
        <div className="section-intro">
          <p className="eyebrow">{architecture.eyebrow}</p>
          <h2>{architecture.title}</h2>
        </div>
        <div className="arch-board" ref={boardRef}>
          <svg className="arch-traces" viewBox="0 0 1000 560" aria-hidden>
            <path
              className="arch-trace-line arch-trace-index"
              pathLength={1}
              d="M250 36 V430 C250 470 250 470 500 470"
            />
            <path
              className="arch-trace-line arch-trace-ask"
              pathLength={1}
              d="M750 36 V430 C750 470 750 470 500 470"
            />
            <path className="arch-trace-line arch-trace-spine" pathLength={1} d="M500 470 V518" />
          </svg>
          <div className="arch-tracks">
            <div className="arch-track">
              <p className="arch-kicker">Index track</p>
              {architecture.index.map((node) => (
                <button
                  className={`arch-node step-1${active === node.id ? " is-active" : ""}`}
                  key={node.id}
                  type="button"
                  onClick={() => select(node.id, true)}
                >
                  <span>{node.title}</span>
                </button>
              ))}
            </div>
            <div className="arch-track">
              <p className="arch-kicker">Ask track</p>
              {architecture.ask.map((node) => (
                <button
                  className={`arch-node step-2${active === node.id ? " is-active" : ""}`}
                  key={node.id}
                  type="button"
                  onClick={() => select(node.id, true)}
                >
                  <span>{node.title}</span>
                </button>
              ))}
            </div>
          </div>
          <button
            className={`arch-spine arch-node${active === "postgres" ? " is-active" : ""}`}
            type="button"
            onClick={() => select("postgres", true)}
          >
            <span className="arch-kicker">Single store</span>
            <strong>{architecture.spine.title}</strong>
          </button>
          <button
            className={`arch-bus arch-node${active === "gateway" ? " is-active" : ""}`}
            type="button"
            onClick={() => select("gateway", true)}
          >
            <span className="arch-kicker">Shared adapters</span>
            <strong>{architecture.bus.title}</strong>
          </button>
          <div className="arch-readout" aria-live="polite">
            <p className="arch-kicker">Survey note</p>
            <h3>{current.title}</h3>
            <p>{current.text}</p>
            <p className="arch-hint">{architecture.readout}</p>
          </div>
        </div>
      </div>
    </section>
  );
}

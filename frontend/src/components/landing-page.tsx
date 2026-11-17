"use client";

import { Github } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import Link from "next/link";
import { useEffect, useState, type MouseEvent } from "react";
import { BRAND_NAME } from "@/api/config";
import { landingContent } from "@/content/landing";
import { LandingArchitecture } from "./landing-architecture";
import { LandingDemo } from "./landing-demo";
import { LandingMetrics } from "./landing-metrics";
import { LandingMotion } from "./landing-motion";
import { LandingPrewarm } from "./landing-prewarm";
import { ThemeToggle } from "./theme-toggle";
import "./landing-page.css";

const ease = [0.22, 1, 0.36, 1] as const;

const navItems = [
  { href: "#how-it-works", id: "how-it-works", label: "How it works" },
  { href: "#trust", id: "trust", label: "Trust" },
  { href: "#architecture", id: "architecture", label: "Architecture" },
  { href: "#numbers", id: "numbers", label: "Measured" },
] as const;

export function LandingPage({ hasHistory: initialHasHistory }: { hasHistory?: boolean }) {
  const [hasHistory, setHasHistory] = useState(initialHasHistory ?? false);
  const [scrolled, setScrolled] = useState(false);
  const [activeSection, setActiveSection] = useState<string>("");
  const reduceMotion = useReducedMotion();

  useEffect(() => {
    void import("@/history/store").then(({ loadHistory }) =>
      loadHistory().then((items) => setHasHistory(items.length > 0)),
    );
  }, []);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const sections = navItems
      .map((item) => document.getElementById(item.id))
      .filter((node): node is HTMLElement => Boolean(node));
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (visible?.target.id) setActiveSection(visible.target.id);
      },
      { rootMargin: "-28% 0px -52% 0px", threshold: [0.15, 0.35, 0.6] },
    );
    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, []);

  const goTo = (id: string) => (event: MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    document.getElementById(id)?.scrollIntoView({
      behavior: reduceMotion ? "auto" : "smooth",
      block: "start",
    });
    history.replaceState(null, "", `#${id}`);
    setActiveSection(id);
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  };

  const primaryLabel = hasHistory ? "Continue" : "Try it live";
  const hover = reduceMotion ? undefined : { y: -1 };

  return (
    <div className="landing-page">
      <LandingMotion />
      <LandingPrewarm />
      <a className="landing-skip" href="#how-it-works">
        Skip to how it works
      </a>
      <header className={`landing-header${scrolled ? " is-scrolled" : ""}`}>
        <div className="landing-header-inner">
          <Link className="brand" href="/" aria-label={`${BRAND_NAME} home`}>
            <span className="brand-mark" aria-hidden>
              ◈
            </span>
            <span className="brand-name">{BRAND_NAME}</span>
          </Link>
          <nav className="landing-nav" aria-label="Landing page navigation">
            {navItems.map((item) => (
              <a
                className={activeSection === item.id ? "is-active" : undefined}
                href={item.href}
                key={item.id}
                onClick={goTo(item.id)}
              >
                {item.label}
              </a>
            ))}
          </nav>
          <div className="landing-actions">
            <a
              className="icon-button landing-github"
              href="https://github.com/RAHULDINDIGALA-32/repo-cartographer"
              target="_blank"
              rel="noreferrer"
              aria-label="GitHub repository"
            >
              <Github size={16} aria-hidden />
            </a>
            <ThemeToggle />
            <motion.div whileHover={hover} transition={{ duration: 0.18, ease }}>
              <Link className="button button-primary" href="/app">
                {primaryLabel}
              </Link>
            </motion.div>
          </div>
        </div>
      </header>

      <main>
        <section className="landing-hero">
          <div className="landing-hero-atmosphere" aria-hidden>
            <div className="landing-grid" />
            <div className="landing-glow landing-glow-sky" />
            <div className="landing-glow landing-glow-lavender" />
          </div>
          <div className="landing-container landing-hero-layout">
            <div className="hero-copy">
              <p className="eyebrow hero-reveal">{landingContent.hero.eyebrow}</p>
              <h1>
                {landingContent.hero.title.split(/(?<=\.)\s+/).map((line, index) => (
                  <span
                    className={`hero-line hero-reveal${index > 0 ? " hero-line-soft" : ""}`}
                    key={line}
                  >
                    {line}
                  </span>
                ))}
              </h1>
              <p className="hero-description hero-reveal">{landingContent.hero.description}</p>
              <div className="hero-actions hero-reveal">
                <motion.div whileHover={hover} transition={{ duration: 0.18, ease }}>
                  <Link className="button button-primary" href="/app">
                    {primaryLabel}
                  </Link>
                </motion.div>
                <a
                  className="button button-secondary"
                  href="#how-it-works"
                  onClick={goTo("how-it-works")}
                >
                  See how it works
                </a>
              </div>
              <p className="hero-note hero-reveal">
                Public repositories only · History stays on your device
              </p>
            </div>
            <LandingDemo />
          </div>
        </section>

        <section className="landing-section" id="how-it-works">
          <div className="landing-container">
            <div className="section-intro">
              <p className="eyebrow">A clear path from code to answer</p>
              <h2>Four steps. Every one inspectable.</h2>
            </div>
            <div className="pipeline">
              <div className="pipeline-rail" aria-hidden>
                <span className="pipeline-progress" />
              </div>
              <div className="step-grid">
                {landingContent.steps.map((step, index) => (
                  <article
                    className={`step-card step-${index + 1} pipeline-stage`}
                    key={step.label}
                  >
                    <span className="step-number">0{index + 1}</span>
                    <h3>{step.label}</h3>
                    <p>{step.text}</p>
                  </article>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="landing-section" id="trust">
          <div className="landing-container split-section">
            <div>
              <p className="eyebrow">Why trust the answer</p>
              <h2>Useful when the answer is yes — and honest when it is not.</h2>
            </div>
            <ul className="check-list">
              {landingContent.trust.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        </section>

        <section className="landing-section" id="features">
          <div className="landing-container">
            <div className="section-intro">
              <p className="eyebrow">Built like a production system</p>
              <h2>Designed for the questions real codebases create.</h2>
            </div>
            <div className="feature-grid">
              {landingContent.features.map(([title, text], index) => (
                <article className={`feature-card feature-${index + 1}`} key={title}>
                  <h3>{title}</h3>
                  <p>{text}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <LandingArchitecture />
        <LandingMetrics />

        <section className="landing-cta">
          <div className="landing-container landing-cta-inner">
            <h2>Bring a question to your codebase.</h2>
            <p>Start with a public GitHub repository and follow every answer back to its source.</p>
            <motion.div whileHover={hover} transition={{ duration: 0.18, ease }}>
              <Link className="button button-primary" href="/app">
                {primaryLabel}
              </Link>
            </motion.div>
          </div>
        </section>
      </main>
      <footer className="landing-footer">
        <span>
          © {new Date().getFullYear()} {BRAND_NAME}
        </span>
        <span>History stays on your device.</span>
        <a
          href="https://github.com/RAHULDINDIGALA-32/repo-cartographer"
          target="_blank"
          rel="noreferrer"
        >
          GitHub
        </a>
        <Link href="/admin">Admin</Link>
      </footer>
    </div>
  );
}

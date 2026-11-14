"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { BRAND_NAME } from "@/api/config";
import { landingContent } from "@/content/landing";
import { LandingDemo } from "./landing-demo";
import { LandingMotion } from "./landing-motion";
import { LandingPrewarm } from "./landing-prewarm";
import { ThemeToggle } from "./theme-toggle";

export function LandingPage({ hasHistory: initialHasHistory }: { hasHistory?: boolean }) {
  const [hasHistory, setHasHistory] = useState(initialHasHistory ?? false);
  useEffect(() => {
    void import("@/history/store").then(({ loadHistory }) =>
      loadHistory().then((items) => setHasHistory(items.length > 0)),
    );
  }, []);
  const primaryLabel = hasHistory ? "Continue" : "Try it live";
  return (
    <div className="landing-page">
      <LandingMotion />
      <LandingPrewarm />
      <header className="landing-header">
        <Link className="brand" href="/" aria-label={`${BRAND_NAME} home`}>
          <span className="brand-mark" aria-hidden>
            ◈
          </span>
          <span className="brand-name">{BRAND_NAME}</span>
        </Link>
        <nav className="landing-nav" aria-label="Landing page navigation">
          <a href="#how-it-works">How it works</a>
          <a href="#trust">Trust</a>
          <a href="#numbers">Measured</a>
        </nav>
        <div className="landing-actions">
          <ThemeToggle />
          <Link className="button button-primary" href="/app">
            {primaryLabel}
          </Link>
        </div>
      </header>

      <main>
        <section className="landing-hero landing-container">
          <div className="hero-copy">
            <p className="eyebrow">{landingContent.hero.eyebrow}</p>
            <h1>{landingContent.hero.title}</h1>
            <p className="hero-description">{landingContent.hero.description}</p>
            <div className="hero-actions">
              <Link className="button button-primary" href="/app">
                {primaryLabel}
              </Link>
              <a className="button button-secondary" href="#how-it-works">
                See how it works
              </a>
            </div>
            <p className="hero-note">Public repositories only · history stays on your device</p>
          </div>
          <LandingDemo />
        </section>

        <section className="landing-section" id="how-it-works">
          <div className="landing-container">
            <p className="eyebrow">A clear path from code to answer</p>
            <h2>Four steps. Every one inspectable.</h2>
            <div className="step-grid">
              {landingContent.steps.map((step, index) => (
                <article className={`step-card step-${index + 1}`} key={step.label}>
                  <span className="step-number">0{index + 1}</span>
                  <h3>{step.label}</h3>
                  <p>{step.text}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="landing-section" id="trust">
          <div className="landing-container split-section">
            <div>
              <p className="eyebrow">Why trust the answer</p>
              <h2>Useful when the answer is yes—and honest when it is not.</h2>
            </div>
            <ul className="check-list">
              {landingContent.trust.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        </section>

        <section className="landing-section">
          <div className="landing-container">
            <p className="eyebrow">Built like a production system</p>
            <h2>Designed for the questions real codebases create.</h2>
            <div className="feature-grid">
              {landingContent.features.map(([title, text]) => (
                <article className="feature-card" key={title}>
                  <h3>{title}</h3>
                  <p>{text}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="landing-section" id="numbers">
          <div className="landing-container">
            <p className="eyebrow">Measured, not guessed</p>
            <h2>Evidence for the trade-offs.</h2>
            <div className="number-grid">
              {landingContent.numbers.map(([value, caption]) => (
                <article key={value}>
                  <strong>{value}</strong>
                  <p>{caption}</p>
                </article>
              ))}
            </div>
            <p className="section-caption">
              Recorded measurements from the project’s Flask and incremental-sync runs; values are
              not production guarantees.
            </p>
          </div>
        </section>

        <section className="landing-section landing-stack">
          <div className="landing-container">
            <p className="eyebrow">The stack</p>
            <div className="stack-list">
              {landingContent.stack.map((item) => (
                <span key={item}>{item}</span>
              ))}
            </div>
          </div>
        </section>

        <section className="landing-cta landing-container">
          <h2>Bring a question to your codebase.</h2>
          <p>Start with a public GitHub repository and follow every answer back to its source.</p>
          <Link className="button button-primary" href="/app">
            {primaryLabel}
          </Link>
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

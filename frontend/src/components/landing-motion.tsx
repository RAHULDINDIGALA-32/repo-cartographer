"use client";

import { useEffect } from "react";

export function LandingMotion() {
  useEffect(() => {
    let disposed = false;
    let cleanup: () => void = () => {};
    const start = async () => {
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
      const [{ gsap }, { ScrollTrigger }] = await Promise.all([
        import("gsap"),
        import("gsap/ScrollTrigger"),
      ]);
      if (disposed) return;
      gsap.registerPlugin(ScrollTrigger);
      const context = gsap.context(() => {
        gsap.fromTo(
          ".hero-reveal",
          { y: 14, opacity: 0.72 },
          { y: 0, opacity: 1, duration: 0.62, stagger: 0.08, ease: "power2.out" },
        );

        gsap.utils.toArray<HTMLElement>(".landing-section").forEach((section) => {
          const targets = section.querySelectorAll(
            ".step-card, .feature-card, .check-list li, .arch-readout",
          );
          if (!targets.length) return;
          gsap.fromTo(
            targets,
            { y: 16, opacity: 0.8 },
            {
              y: 0,
              opacity: 1,
              duration: 0.48,
              stagger: 0.05,
              ease: "power2.out",
              scrollTrigger: { trigger: section, start: "top 84%", once: true },
            },
          );
        });

        const pipeline = document.querySelector(".pipeline");
        const progress = document.querySelector(".pipeline-progress");
        if (pipeline && progress) {
          gsap.fromTo(
            progress,
            { scaleX: 0 },
            {
              scaleX: 1,
              ease: "none",
              scrollTrigger: {
                trigger: pipeline,
                start: "top 75%",
                end: "bottom 55%",
                scrub: 0.4,
              },
            },
          );
        }
      });
      cleanup = () => {
        context.revert();
      };
    };
    const hasIdleCallback = typeof window.requestIdleCallback === "function";
    const idle = hasIdleCallback
      ? window.requestIdleCallback(start)
      : window.setTimeout(start, 250);
    const onLoad = () => {
      void import("gsap/ScrollTrigger").then(({ ScrollTrigger }) => ScrollTrigger.refresh());
    };
    window.addEventListener("load", onLoad);
    return () => {
      disposed = true;
      window.removeEventListener("load", onLoad);
      if (hasIdleCallback) window.cancelIdleCallback(idle as number);
      else window.clearTimeout(idle as number);
      cleanup();
    };
  }, []);
  return null;
}

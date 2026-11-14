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
          ".hero-copy > *",
          { y: 12, opacity: 0.7 },
          { y: 0, opacity: 1, duration: 0.6, stagger: 0.07, ease: "power2.out" },
        );
        gsap.utils.toArray<HTMLElement>(".landing-section").forEach((section) => {
          gsap.fromTo(
            section,
            { y: 16, opacity: 0.82 },
            {
              y: 0,
              opacity: 1,
              duration: 0.55,
              ease: "power2.out",
              scrollTrigger: { trigger: section, start: "top 86%", once: true },
            },
          );
        });
      });
      cleanup = () => {
        context.revert();
      };
    };
    const hasIdleCallback = typeof window.requestIdleCallback === "function";
    const idle = hasIdleCallback
      ? window.requestIdleCallback(start)
      : window.setTimeout(start, 250);
    return () => {
      disposed = true;
      if (hasIdleCallback) window.cancelIdleCallback(idle as number);
      else window.clearTimeout(idle as number);
      cleanup();
    };
  }, []);
  return null;
}

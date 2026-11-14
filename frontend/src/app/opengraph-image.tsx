import { ImageResponse } from "next/og";

export const alt = "Repo Cartographer — Ask your codebase. Verify every answer.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpenGraphImage() {
  return new ImageResponse(
    <div
      style={{
        background: "#ffffff",
        color: "#0a0a0a",
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        padding: "80px",
        fontFamily: "sans-serif",
      }}
    >
      <div style={{ fontSize: 28, letterSpacing: 2, color: "#71717a" }}>REPO CARTOGRAPHER</div>
      <div style={{ fontSize: 74, fontWeight: 700, letterSpacing: -4, marginTop: 28 }}>
        Ask your codebase.
      </div>
      <div style={{ fontSize: 74, fontWeight: 700, letterSpacing: -4 }}>Verify every answer.</div>
      <div style={{ fontSize: 26, color: "#52525b", marginTop: 35 }}>
        Cited, commit-pinned answers from public GitHub repositories.
      </div>
    </div>,
    { ...size },
  );
}

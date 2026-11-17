import { ImageResponse } from "next/og";

export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#ffffff",
      }}
    >
      <div
        style={{
          width: 148,
          height: 148,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          border: "8px solid #000000",
          borderRadius: 40,
          color: "#000000",
          fontSize: 88,
          lineHeight: 1,
        }}
      >
        ◈
      </div>
    </div>,
    { ...size },
  );
}

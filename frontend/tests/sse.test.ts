import { describe, expect, it } from "vitest";
import { splitSseFrames, parseSseFrame } from "../src/api/client";

describe("SSE parser", () => {
  it("handles CRLF and keeps an incomplete frame", () => {
    const result = splitSseFrames('event: token\r\ndata: {"text":"hi"}\r\n\r\nevent: done\ndata:');
    expect(result.frames).toHaveLength(1);
    expect(parseSseFrame(result.frames[0]!)).toEqual({ event: "token", data: '{"text":"hi"}' });
    expect(result.remainder).toContain("event: done");
  });
  it("joins multiline data and ignores heartbeats", () => {
    expect(parseSseFrame(": ping\n\nevent: status\ndata: {\ndata: 1")).toEqual({
      event: "status",
      data: "{\n1",
    });
  });
});

const rawBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;

if (typeof window !== "undefined" && process.env.NODE_ENV === "development" && !rawBaseUrl) {
  console.warn("NEXT_PUBLIC_API_BASE_URL is not set; using http://localhost:8000");
}

export const API_BASE_URL = (rawBaseUrl || "http://localhost:8000").replace(/\/$/, "");

export const BRAND_NAME = process.env.NEXT_PUBLIC_BRAND_NAME || "repo-cartographer";

export const MAX_QUESTION_CHARS = 16_000;

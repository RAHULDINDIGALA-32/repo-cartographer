import type { Turn } from "@/hooks/use-ask";

export const HISTORY_VERSION = 1;
const DB_NAME = "repo-cartographer";
const STORE = "turns";
const MAX_TURNS = 100;
const MAX_SNIPPET = 8_000;
const MAX_BYTES = 5_000_000;

export type HistoryRecord = Turn & { schemaVersion: number };
let memory: HistoryRecord[] = [];

function compact(turn: Turn): HistoryRecord {
  return {
    ...turn,
    schemaVersion: HISTORY_VERSION,
    citations: turn.citations.map((item) => ({
      ...item,
      snippet: item.snippet?.slice(0, MAX_SNIPPET),
    })),
  };
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") return reject(new Error("IndexedDB unavailable"));
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE, { keyPath: "id" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("Could not open history"));
  });
}

async function readAll(): Promise<HistoryRecord[]> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const request = db.transaction(STORE, "readonly").objectStore(STORE).getAll();
    request.onsuccess = () =>
      resolve((request.result as HistoryRecord[]).sort((a, b) => a.createdAt - b.createdAt));
    request.onerror = () => reject(request.error ?? new Error("Could not load history"));
  });
}

export async function loadHistory(): Promise<HistoryRecord[]> {
  try {
    memory = await readAll();
    return memory;
  } catch {
    return memory;
  }
}

export async function saveTurn(turn: Turn): Promise<void> {
  const record = compact(turn);
  memory = [...memory.filter((item) => item.id !== record.id), record]
    .sort((a, b) => a.createdAt - b.createdAt)
    .slice(-MAX_TURNS);
  try {
    const db = await openDb();
    await new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(STORE, "readwrite");
      transaction.objectStore(STORE).put(record);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
    });
    const all = await readAll();
    const bytes = new Blob([JSON.stringify(all)]).size;
    if (bytes > MAX_BYTES || all.length > MAX_TURNS) {
      const trim = all.slice(-MAX_TURNS);
      const tx = db.transaction(STORE, "readwrite");
      for (const item of all.slice(0, -MAX_TURNS)) tx.objectStore(STORE).delete(item.id);
      memory = trim;
    }
  } catch {
    /* Storage is optional; memory fallback keeps the session usable. */
  }
}

export async function deleteTurn(id: string) {
  memory = memory.filter((item) => item.id !== id);
  try {
    const db = await openDb();
    db.transaction(STORE, "readwrite").objectStore(STORE).delete(id);
  } catch {
    /* optional storage */
  }
}

export async function clearHistory() {
  memory = [];
  try {
    const db = await openDb();
    db.transaction(STORE, "readwrite").objectStore(STORE).clear();
  } catch {
    /* optional storage */
  }
}

export function searchHistory(records: HistoryRecord[], query: string) {
  const value = query.trim().toLowerCase();
  return value ? records.filter((turn) => turn.question.toLowerCase().includes(value)) : records;
}

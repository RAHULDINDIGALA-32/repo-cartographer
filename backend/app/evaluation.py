from __future__ import annotations

import csv
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ALLOWED_CATEGORIES = {
    "identifier",
    "paraphrase",
    "locate",
    "explain",
    "trace_flow",
    "config",
    "docs",
    "tests",
    "unanswerable",
}
ALLOWED_SPLITS = {"tune", "heldout"}


def validate_questions(items: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    ids: set[str] = set()
    counts = {category: 0 for category in ALLOWED_CATEGORIES}
    splits = {split: 0 for split in ALLOWED_SPLITS}
    for index, item in enumerate(items):
        prefix = f"questions[{index}]"
        question_id = item.get("id")
        if not isinstance(question_id, str) or not question_id:
            errors.append(f"{prefix}.id must be non-empty")
        elif question_id in ids:
            errors.append(f"duplicate id: {question_id}")
        else:
            ids.add(question_id)
        if item.get("category") not in ALLOWED_CATEGORIES:
            errors.append(f"{prefix}.category is invalid")
        else:
            counts[item["category"]] += 1
        if item.get("split") not in ALLOWED_SPLITS:
            errors.append(f"{prefix}.split is invalid")
        else:
            splits[item["split"]] += 1
        if not isinstance(item.get("repo"), str) or not item["repo"]:
            errors.append(f"{prefix}.repo is required")
        if not isinstance(item.get("question"), str) or not item["question"]:
            errors.append(f"{prefix}.question is required")
        gold = item.get("gold")
        if not isinstance(gold, list):
            errors.append(f"{prefix}.gold must be a list")
            gold = []
        if item.get("answerable") and not gold:
            errors.append(f"{prefix}.answerable questions require gold evidence")
        if not item.get("answerable") and gold:
            errors.append(f"{prefix}.unanswerable questions must not have gold evidence")
        for evidence in gold:
            if not isinstance(evidence, dict) or not isinstance(evidence.get("path"), str):
                errors.append(f"{prefix}.gold entries require path")
            lines = evidence.get("lines") if isinstance(evidence, dict) else None
            if lines is not None and (
                not isinstance(lines, list)
                or len(lines) != 2
                or not all(isinstance(value, int) for value in lines)
                or lines[0] < 1
                or lines[1] < lines[0]
            ):
                errors.append(f"{prefix}.gold.lines must be [start,end]")
    warnings = []
    if len(items) < 40:
        warnings.append("gold set has fewer than the B5 minimum of 40 questions")
    if splits["heldout"] == 0:
        warnings.append("gold set has no heldout questions")
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "counts": counts,
        "splits": splits,
        "questions": len(items),
    }


def gold_matches(hit, gold: dict[str, Any]) -> bool:
    chunk = hit.chunk if hasattr(hit, "chunk") else hit
    path = chunk.path if hasattr(chunk, "path") else chunk.get("path")
    start_line = chunk.start_line if hasattr(chunk, "start_line") else chunk.get("start_line")
    end_line = chunk.end_line if hasattr(chunk, "end_line") else chunk.get("end_line")
    if path != gold["path"]:
        return False
    lines = gold.get("lines")
    return lines is None or (start_line <= lines[1] and end_line >= lines[0])


def retrieval_metrics(
    hits, gold: list[dict[str, Any]], context=None, ks=(1, 3, 5, 8, 20)
) -> dict[str, Any]:
    answerable = bool(gold)
    result: dict[str, Any] = {"answerable": answerable, "gold_count": len(gold)}
    if not answerable:
        result["top_score"] = (
            hits[0].score
            if hits and hasattr(hits[0], "score")
            else hits[0].get("score")
            if hits
            else None
        )
        return result
    for k in ks:
        selected = hits[:k]
        matched = {
            index
            for index, item in enumerate(gold)
            if any(gold_matches(hit, item) for hit in selected)
        }
        result[f"hit@{k}"] = int(bool(matched))
        result[f"recall@{k}"] = len(matched) / len(gold)
    result["mrr"] = next(
        (
            1 / rank
            for rank, hit in enumerate(hits[:20], 1)
            if any(gold_matches(hit, item) for item in gold)
        ),
        0,
    )
    context = context or []
    result["context_recall"] = len(
        {
            index
            for index, item in enumerate(gold)
            if any(gold_matches(block, item) for block in context)
        }
    ) / len(gold)
    return result


def bootstrap_ci(values: list[float], *, seed: int = 17, samples: int = 2000) -> list[float] | None:
    """Deterministic percentile bootstrap interval for small evaluation sets."""
    if not values:
        return None
    rng = random.Random(seed)
    means = [sum(rng.choice(values) for _ in values) / len(values) for _ in range(samples)]
    means.sort()
    return [means[int(0.025 * (samples - 1))], means[int(0.975 * (samples - 1))]]


def paired_comparison(
    candidate: list[dict], baseline: list[dict], metric: str = "hit@5"
) -> dict[str, int]:
    left = {row["id"]: row.get("metrics", {}).get(metric, 0) for row in candidate}
    right = {row["id"]: row.get("metrics", {}).get(metric, 0) for row in baseline}
    shared = sorted(left.keys() & right.keys())
    return {
        "wins": sum(left[item] > right[item] for item in shared),
        "losses": sum(left[item] < right[item] for item in shared),
        "ties": sum(left[item] == right[item] for item in shared),
        "questions": len(shared),
    }


def evaluation_summary(rows: list[dict], *, stage: str = "metrics") -> dict[str, Any]:
    key = "ranked_metrics" if stage == "ranked" else "metrics"
    answerable = [
        row[key]
        for row in rows
        if "error" not in row and row.get(key, {}).get("answerable")
    ]
    summary: dict[str, Any] = {"stage": stage, "answerable": len(answerable)}
    for metric in ("hit@5", "mrr", "context_recall"):
        values = [float(row[metric]) for row in answerable if metric in row]
        if values:
            summary[metric] = {
                "mean": sum(values) / len(values),
                "count": len(values),
                "ci95": bootstrap_ci(values),
            }
    return summary


@dataclass
class JsonCache:
    path: Path

    def __post_init__(self):
        self.values = (
            json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        )

    def get(self, key):
        return self.values.get(key)

    def put(self, key, value):
        self.values[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.values, sort_keys=True), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=sorted({key for row in rows for key in row}))
        writer.writeheader()
        writer.writerows(rows)

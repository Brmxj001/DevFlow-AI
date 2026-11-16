from __future__ import annotations

import asyncio
import contextvars
import json
import math
import os
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import settings  # noqa: E402
from app.services.context_compression import estimate_tokens, prompt_cache_model_kwargs  # noqa: E402

RESULTS_DIR = ROOT / "experiments" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

CASE_ID: contextvars.ContextVar[str] = contextvars.ContextVar("case_id", default="-")
PURPOSE: contextvars.ContextVar[str] = contextvars.ContextVar("purpose", default="general")
MAX_TOKENS: contextvars.ContextVar[int] = contextvars.ContextVar("max_tokens", default=2500)
REPAIR_SCHEMA: contextvars.ContextVar[Any] = contextvars.ContextVar("repair_schema", default=None)

REPAIR_SYSTEM = """你是严格的结构化输出修复器。
给定目标 JSON Schema、原始模型输出和校验错误，返回一个符合 Schema 的 JSON 对象。
必须保留原始输出中的事实、结论和列表内容，只修复字段缺失、字段名和类型问题。
不要编造原始输出中没有的事实。只返回 JSON。"""


class RecordingLLM:
    """LLMClient-compatible client that records provider usage and latency."""

    def __init__(self, *, concurrency: int = 8, max_retries: int = 3) -> None:
        self.base_url = settings.llm_base_url.rstrip("/")
        self.api_key = settings.llm_api_key
        self.model = os.getenv("EXPERIMENT_MODEL") or settings.llm_model
        self.calls: list[dict[str, Any]] = []
        self.semaphore = asyncio.Semaphore(concurrency)
        self.max_retries = max_retries
        self.repairs = 0
        self.retries = 0
        self.normalizations = 0

    def reset(self) -> None:
        self.calls = []
        self.repairs = 0
        self.retries = 0
        self.normalizations = 0

    def totals(self) -> dict[str, Any]:
        prompts = sum(int(item.get("prompt_tokens") or 0) for item in self.calls)
        completions = sum(int(item.get("completion_tokens") or 0) for item in self.calls)
        return {
            "calls": len(self.calls),
            "prompt_tokens": prompts,
            "completion_tokens": completions,
            "total_tokens": prompts + completions,
            "errors": sum(1 for item in self.calls if item.get("error")),
        }

    async def chat_json(self, system_prompt: str, user_payload: dict[str, Any]) -> dict[str, Any]:
        content = await self._call(
            system_prompt,
            json.dumps(user_payload, ensure_ascii=False),
            json_mode=True,
        )
        parsed = _parse_json_object(content)
        if not parsed and content.strip():
            self.retries += 1
            retry_content = await self._call(
                system_prompt,
                json.dumps(user_payload, ensure_ascii=False)
                + "\n\n上一次输出不是完整 JSON，请返回完整、合法的 JSON 对象。",
                json_mode=True,
                max_tokens_override=max(5000, int(MAX_TOKENS.get()) + 1500),
            )
            parsed = _parse_json_object(retry_content)
        schema = REPAIR_SCHEMA.get()
        if schema is None or not parsed:
            return parsed
        normalized = normalize_payload(schema, parsed)
        if normalized != parsed:
            self.normalizations += 1
        return normalized

    async def chat_text(self, system_prompt: str, user_message: str) -> str:
        return await self._call(system_prompt, user_message, json_mode=False)

    async def _call(
        self,
        system_prompt: str,
        user_message: str,
        *,
        json_mode: bool,
        purpose: str | None = None,
        max_tokens_override: int | None = None,
    ) -> str:
        if not self.api_key:
            raise RuntimeError("LLM_API_KEY is not configured")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        payload["max_tokens"] = max(256, int(max_tokens_override or MAX_TOKENS.get()))
        payload.update(prompt_cache_model_kwargs())

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            started = time.perf_counter()
            record: dict[str, Any] = {
                "case_id": CASE_ID.get(),
                "purpose": purpose or PURPOSE.get(),
                "attempt": attempt,
                "json_mode": json_mode,
                "model": self.model,
            }
            try:
                async with self.semaphore:
                    async with httpx.AsyncClient(timeout=180) as client:
                        response = await client.post(
                            f"{self.base_url}/chat/completions",
                            headers={"Authorization": f"Bearer {self.api_key}"},
                            json=payload,
                        )
                        response.raise_for_status()
                        data = response.json()
                content = str(data["choices"][0]["message"].get("content") or "")
                if not content.strip():
                    raise RuntimeError("empty completion content")
                usage = data.get("usage") or {}
                prompt_tokens = int(usage.get("prompt_tokens") or estimate_tokens(system_prompt + user_message))
                completion_tokens = int(usage.get("completion_tokens") or estimate_tokens(content))
                record.update(
                    {
                        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": prompt_tokens + completion_tokens,
                        "usage_source": "provider" if usage else "estimate",
                        "finish_reason": data["choices"][0].get("finish_reason"),
                        "raw_chars": len(content),
                        "raw_preview": content[:2000],
                        "error": None,
                    }
                )
                self.calls.append(record)
                return content
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                record.update(
                    {
                        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                        "prompt_tokens": estimate_tokens(system_prompt + user_message),
                        "completion_tokens": 0,
                        "total_tokens": estimate_tokens(system_prompt + user_message),
                        "usage_source": "estimate",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                self.calls.append(record)
                if attempt < self.max_retries:
                    await asyncio.sleep(min(8.0, 1.5 * attempt))
        raise RuntimeError(f"LLM call failed after {self.max_retries} attempts: {last_error}")


def _parse_json_object(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return {}
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        lines = [line.strip(" -\t") for line in value.splitlines() if line.strip()]
        return lines or ([value.strip()] if value.strip() else [])
    if value is None:
        return []
    return [value]


def _as_str_list(value: Any) -> list[str]:
    return [str(item) if not isinstance(item, dict) else json.dumps(item, ensure_ascii=False) for item in _as_list(value) if item is not None]


def _as_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1", "是", "有", "blocking", "block"}:
            return True
        if lowered in {"false", "no", "0", "否", "没有", "non-blocking"}:
            return False
    return default


def _as_float(value: Any, default: float = 0.5) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))


def _pick_enum(value: Any, mapping: dict[str, str]) -> str | None:
    text = str(value or "").strip().lower()
    return mapping.get(text)


ISSUE_CATEGORY = {
    "bug": "Bug",
    "feature": "Feature",
    "documentation": "Documentation",
    "docs": "Documentation",
    "doc": "Documentation",
    "test": "Test",
    "tests": "Test",
    "ops": "Ops",
    "operations": "Ops",
    "infra": "Ops",
    "refactor": "Refactor",
    "refactoring": "Refactor",
    "question": "Question",
    "q&a": "Question",
}
ISSUE_CONCLUSION = {
    "进入开发": "进入开发",
    "start": "进入开发",
    "implement": "进入开发",
    "等待澄清": "等待澄清",
    "wait": "等待澄清",
    "clarify": "等待澄清",
    "关闭": "关闭",
    "close": "关闭",
    "拆分": "拆分",
    "split": "拆分",
    "合并到已有 issue": "合并到已有 Issue",
    "merge": "合并到已有 Issue",
}
PRIORITY = {"p0": "P0", "p1": "P1", "p2": "P2", "p3": "P3", "critical": "P0", "high": "P1", "medium": "P2", "low": "P3"}
COMPLEXITY = {"s": "S", "m": "M", "l": "L", "xl": "XL", "small": "S", "medium": "M", "large": "L", "xlarge": "XL"}
MERGE_RECOMMENDATION = {
    "建议合入": "建议合入",
    "merge": "建议合入",
    "approve": "建议合入",
    "修改后合入": "修改后合入",
    "changes requested": "修改后合入",
    "暂缓": "暂缓",
    "hold": "暂缓",
    "defer": "暂缓",
    "拒绝": "拒绝",
    "reject": "拒绝",
}
SEVERITY = {"p1": "P1", "p2": "P2", "p3": "P3", "high": "P1", "critical": "P1", "medium": "P2", "warning": "P2", "low": "P3", "info": "P3"}
FAILURE_TYPE = {
    "test": "test",
    "testing": "test",
    "build": "build",
    "compilation": "build",
    "compile": "build",
    "lint": "lint",
    "format": "lint",
    "style": "lint",
    "dependency": "dependency",
    "dependencies": "dependency",
    "deps": "dependency",
    "install": "dependency",
    "permission": "permission",
    "auth": "permission",
    "access": "permission",
    "environment": "environment",
    "env": "environment",
    "config": "environment",
    "unknown": "unknown",
}


def _normalize_evidence(value: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in _as_list(value):
        if isinstance(item, dict):
            output.append(
                {
                    "source_type": _text(item.get("source_type") or item.get("type") or "issue"),
                    "title": _text(item.get("title") or item.get("name") or "evidence"),
                    "snippet": _text(item.get("snippet") or item.get("content") or item.get("evidence")),
                    "reference": None if item.get("reference") in (None, "") else _text(item.get("reference")),
                    "confidence": None if item.get("confidence") in (None, "") else _as_float(item.get("confidence")),
                }
            )
        elif item is not None:
            text = _text(item)
            output.append({"source_type": "issue", "title": text[:120], "snippet": text, "reference": None, "confidence": None})
    return output


def _normalize_issue(raw: dict[str, Any]) -> dict[str, Any]:
    data = dict(raw)
    for key in ("summary", "conclusion_reason", "suggested_owner", "owner_reason"):
        if key in data and not isinstance(data[key], str):
            data[key] = _text(data[key])
    for key, mapping in (("category", ISSUE_CATEGORY), ("conclusion", ISSUE_CONCLUSION), ("priority", PRIORITY), ("complexity", COMPLEXITY)):
        if key in data:
            resolved = _pick_enum(data[key], mapping)
            if resolved:
                data[key] = resolved
            else:
                data.pop(key, None)
    if "evidence" in data:
        data["evidence"] = _normalize_evidence(data["evidence"])
    if "checklist" in data:
        data["checklist"] = _as_str_list(data["checklist"])
    if "action_items" in data:
        data["action_items"] = _as_str_list(data["action_items"])
    if "duplicate_candidates" in data:
        candidates = []
        for item in _as_list(data["duplicate_candidates"]):
            if isinstance(item, dict) and item.get("title"):
                candidates.append(
                    {
                        "issue_id": _text(item.get("issue_id") or item.get("id") or ""),
                        "title": _text(item.get("title")),
                        "score": _as_float(item.get("score"), 0.5),
                    }
                )
        data["duplicate_candidates"] = candidates
    if "drafts" in data:
        drafts = data["drafts"]
        if isinstance(drafts, str):
            data["drafts"] = {"clarification_comment": drafts, "task_breakdown": None}
        elif isinstance(drafts, dict):
            data["drafts"] = {
                "clarification_comment": None if drafts.get("clarification_comment") in (None, "") else _text(drafts.get("clarification_comment")),
                "task_breakdown": None if drafts.get("task_breakdown") in (None, "") else _text(drafts.get("task_breakdown")),
            }
        elif drafts is None:
            data.pop("drafts", None)
    if "confidence" in data:
        data["confidence"] = _as_float(data["confidence"])
    return data


def _normalize_findings(value: Any) -> list[dict[str, Any]]:
    output = []
    for item in _as_list(value):
        if not isinstance(item, dict):
            continue
        severity = _pick_enum(item.get("severity"), SEVERITY) or "P2"
        output.append(
            {
                "severity": severity,
                "title": _text(item.get("title") or item.get("name") or "finding"),
                "evidence": _text(item.get("evidence") or item.get("reason") or item.get("description")),
                "required_action": _text(item.get("required_action") or item.get("action") or item.get("recommendation")),
                "blocking": _as_bool(item.get("blocking"), severity in {"P1", "P2"}),
            }
        )
    return output


def _normalize_pr(raw: dict[str, Any]) -> dict[str, Any]:
    data = dict(raw)
    for key in ("summary", "recommendation_reason"):
        if key in data and not isinstance(data[key], str):
            data[key] = _text(data[key])
    for key in (
        "plan",
        "executed_steps",
        "key_changes",
        "risk_points",
        "blocking_issues",
        "review_checklist",
        "test_suggestions",
        "files_need_attention",
        "review_comments",
    ):
        if key in data:
            data[key] = _as_str_list(data[key])
    if "review_findings" in data:
        data["review_findings"] = _normalize_findings(data["review_findings"])
    if "merge_recommendation" in data:
        resolved = _pick_enum(data["merge_recommendation"], MERGE_RECOMMENDATION)
        if resolved:
            data["merge_recommendation"] = resolved
        else:
            data.pop("merge_recommendation", None)
    if "confidence" in data:
        data["confidence"] = _as_float(data["confidence"])
    return data


def _normalize_ci(raw: dict[str, Any]) -> dict[str, Any]:
    data = dict(raw)
    for key in ("failure_summary", "root_cause", "blocking_reason"):
        if key in data and not isinstance(data[key], str):
            data[key] = _text(data[key])
    for key in ("plan", "executed_steps", "possible_causes", "fix_steps", "debug_steps", "related_files"):
        if key in data:
            data[key] = _as_str_list(data[key])
    if "first_error" in data and data["first_error"] is not None:
        data["first_error"] = _text(data["first_error"])
    if "failure_type" in data:
        resolved = _pick_enum(data["failure_type"], FAILURE_TYPE)
        if resolved:
            data["failure_type"] = resolved
        else:
            data.pop("failure_type", None)
    if "is_merge_blocking" in data:
        data["is_merge_blocking"] = _as_bool(data["is_merge_blocking"], True)
    if "confidence" in data:
        data["confidence"] = _as_float(data["confidence"])
    return data


def normalize_payload(schema: Any, raw: dict[str, Any]) -> dict[str, Any]:
    name = getattr(schema, "__name__", "")
    try:
        if name == "IssueAnalysisOutput":
            return _normalize_issue(raw)
        if name == "PRReviewOutput":
            return _normalize_pr(raw)
        if name == "CIDebugOutput":
            return _normalize_ci(raw)
    except Exception:  # noqa: BLE001
        return raw
    return raw


def mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def pstdev(values: list[float]) -> float:
    return round(statistics.pstdev(values), 4) if len(values) > 1 else 0.0


def macro_f1(y_true: list[str], y_pred: list[str], labels: list[str]) -> dict[str, Any]:
    per_label: dict[str, dict[str, float]] = {}
    for label in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == label and p == label)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != label and p == label)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == label and p != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_label[label] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": tp + fn,
        }
    return {
        "macro_f1": round(mean([item["f1"] for item in per_label.values()]), 4),
        "accuracy": round(sum(1 for t, p in zip(y_true, y_pred) if t == p) / max(len(y_true), 1), 4),
        "per_label": per_label,
    }


def recall_at_k(relevant: set[str], ranked: list[str], k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(ranked[:k]) & relevant) / len(relevant)


def mrr_at_k(relevant: set[str], ranked: list[str], k: int) -> float:
    for index, item in enumerate(ranked[:k], start=1):
        if item in relevant:
            return 1.0 / index
    return 0.0


def ndcg_at_k(relevant: set[str], ranked: list[str], k: int) -> float:
    actual = sum(1.0 / math.log2(index + 2) for index, item in enumerate(ranked[:k]) if item in relevant)
    ideal_hits = min(len(relevant), k)
    ideal = sum(1.0 / math.log2(index + 2) for index in range(ideal_hits))
    return actual / ideal if ideal else 0.0


def write_json(name: str, payload: Any) -> Path:
    path = RESULTS_DIR / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def read_json(name: str) -> Any:
    return json.loads((RESULTS_DIR / name).read_text(encoding="utf-8"))


def print_table(rows: list[dict[str, Any]], columns: list[str]) -> None:
    widths: dict[str, int] = {}
    for column in columns:
        candidates = [len(column)]
        for row in rows:
            value = row.get(column, "")
            candidates.append(len(f"{value:.4f}") if isinstance(value, float) else len(str(value)))
        widths[column] = max(candidates)
    print(" | ".join(column.ljust(widths[column]) for column in columns))
    print("-+-".join("-" * widths[column] for column in columns))
    for row in rows:
        cells = []
        for column in columns:
            value = row.get(column, "")
            if isinstance(value, float):
                cells.append(f"{value:.4f}".ljust(widths[column]))
            else:
                cells.append(str(value).ljust(widths[column]))
        print(" | ".join(cells))

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from common import (
    CASE_ID,
    MAX_TOKENS,
    PURPOSE,
    REPAIR_SCHEMA,
    RecordingLLM,
    macro_f1,
    mean,
    write_json,
)
from datasets import CI_CASES, ISSUE_CASES, PR_CASES

from app.schemas.analysis import CIDebugOutput, IssueAnalysisOutput, PRReviewOutput
from app.services.agents.ci_debug_agent import CIDebugAgent
from app.services.agents.issue_agent import IssueAgent
from app.services.agents.pr_review_agent import PRReviewAgent
from app.services.rag.chunking import chunk_pr_files

ISSUE_LABELS = ["Bug", "Feature", "Documentation", "Test", "Ops", "Refactor", "Question"]

STRONG_BUG_KEYWORDS = [
    "sql", "注入", "injection", "授权", "权限", "authorization", "permission",
    "未校验", "secret", "密钥", "硬编码", "hardcoded", "空指针", "null dereference",
    "off-by-one", "race", "并发", "竞争", "traversal", "路径穿越", "xss", "跨站",
    "反序列化", "pickle", "内存泄漏", "memory leak", "leak", "n+1", "循环查询",
    "默认值", "迁移", "migration",
]

GENERIC_PHRASES = [
    "边界条件和异常路径",
    "缺少测试覆盖证明",
    "敏感文件变更需要重点验证",
    "失败 ci 阻塞合并",
    "review 评论尚需确认",
]


def _lower(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str).lower()


def _clean_text(text: str) -> str:
    value = text.lower()
    for phrase in GENERIC_PHRASES:
        value = value.replace(phrase.lower(), " ")
    return value


async def _run_issue(llm: RecordingLLM, case: dict[str, Any]) -> dict[str, Any]:
    CASE_ID.set(case["id"])
    PURPOSE.set("issue_agent")
    MAX_TOKENS.set(2500)
    REPAIR_SCHEMA.set(IssueAnalysisOutput)
    started = time.perf_counter()
    try:
        output = await asyncio.wait_for(IssueAgent(llm=llm).run(case["issue"], {}), timeout=120)
        return {
            "id": case["id"],
            "expected": case["expected_category"],
            "predicted": output.get("category"),
            "correct": output.get("category") == case["expected_category"],
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "output": output,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "id": case["id"],
            "expected": case["expected_category"],
            "predicted": None,
            "correct": False,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "output": {},
            "error": f"{type(exc).__name__}: {exc}",
        }


async def _run_pr(llm: RecordingLLM, case: dict[str, Any]) -> dict[str, Any]:
    CASE_ID.set(case["id"])
    PURPOSE.set("pr_review_agent")
    MAX_TOKENS.set(3000)
    REPAIR_SCHEMA.set(PRReviewOutput)
    started = time.perf_counter()
    try:
        output = await asyncio.wait_for(PRReviewAgent(llm=llm).run(case["pr"], {}), timeout=120)
        findings = output.get("review_findings") or []
        finding_text = _clean_text(
            "\n".join(
                " ".join(str(item.get(key) or "") for key in ("title", "evidence", "required_action"))
                for item in findings
                if isinstance(item, dict)
            )
            + "\n"
            + "\n".join(str(item) for item in output.get("blocking_issues") or [])
        )
        if case["has_bug"]:
            detected = any(keyword.lower() in finding_text for keyword in case["bug_keywords"])
        else:
            detected = any(keyword.lower() in finding_text for keyword in STRONG_BUG_KEYWORDS)
        return {
            "id": case["id"],
            "has_bug": case["has_bug"],
            "bug_type": case["bug_type"],
            "detected": detected,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "merge_recommendation": output.get("merge_recommendation"),
            "finding_text": finding_text[:1200],
            "output": output,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "id": case["id"],
            "has_bug": case["has_bug"],
            "bug_type": case["bug_type"],
            "detected": False,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "merge_recommendation": None,
            "finding_text": "",
            "output": {},
            "error": f"{type(exc).__name__}: {exc}",
        }


async def _run_ci(llm: RecordingLLM, case: dict[str, Any]) -> dict[str, Any]:
    CASE_ID.set(case["id"])
    PURPOSE.set("ci_debug_agent")
    MAX_TOKENS.set(2000)
    REPAIR_SCHEMA.set(CIDebugOutput)
    started = time.perf_counter()
    try:
        output = await asyncio.wait_for(CIDebugAgent(llm=llm).run(case["workflow_run"], {}), timeout=120)
        root_cause = str(output.get("root_cause") or "").lower()
        hit = any(keyword.lower() in root_cause for keyword in case["expected_root_keywords"])
        return {
            "id": case["id"],
            "expected_failure_type": case["expected_failure_type"],
            "predicted_failure_type": output.get("failure_type"),
            "failure_type_correct": output.get("failure_type") == case["expected_failure_type"],
            "root_cause_hit": hit,
            "root_cause": output.get("root_cause"),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "output": output,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "id": case["id"],
            "expected_failure_type": case["expected_failure_type"],
            "predicted_failure_type": None,
            "failure_type_correct": False,
            "root_cause_hit": False,
            "root_cause": None,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "output": {},
            "error": f"{type(exc).__name__}: {exc}",
        }


async def main() -> None:
    llm = RecordingLLM(concurrency=8)
    started = time.perf_counter()
    issue_rows, pr_rows, ci_rows = await asyncio.gather(
        asyncio.gather(*(_run_issue(llm, case) for case in ISSUE_CASES)),
        asyncio.gather(*(_run_pr(llm, case) for case in PR_CASES)),
        asyncio.gather(*(_run_ci(llm, case) for case in CI_CASES)),
    )
    elapsed = round(time.perf_counter() - started, 2)

    issue_metrics = macro_f1(
        [row["expected"] for row in issue_rows],
        [row["predicted"] or "UNKNOWN" for row in issue_rows],
        ISSUE_LABELS,
    )
    tp = sum(1 for row in pr_rows if row["has_bug"] and row["detected"])
    fn = sum(1 for row in pr_rows if row["has_bug"] and not row["detected"])
    fp = sum(1 for row in pr_rows if not row["has_bug"] and row["detected"])
    tn = sum(1 for row in pr_rows if not row["has_bug"] and not row["detected"])
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    pr_metrics = {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
        "accuracy": round((tp + tn) / max(len(pr_rows), 1), 4),
    }
    ci_metrics = {
        "failure_type_accuracy": round(
            sum(1 for row in ci_rows if row["failure_type_correct"]) / max(len(ci_rows), 1), 4
        ),
        "root_cause_top1": round(sum(1 for row in ci_rows if row["root_cause_hit"]) / max(len(ci_rows), 1), 4),
        "by_type": {},
    }
    for failure_type in sorted({row["expected_failure_type"] for row in ci_rows}):
        group = [row for row in ci_rows if row["expected_failure_type"] == failure_type]
        ci_metrics["by_type"][failure_type] = {
            "n": len(group),
            "failure_type_accuracy": round(sum(1 for row in group if row["failure_type_correct"]) / len(group), 4),
            "root_cause_top1": round(sum(1 for row in group if row["root_cause_hit"]) / len(group), 4),
        }

    errors = {
        "issue": [row["id"] for row in issue_rows if row["error"]],
        "pr": [row["id"] for row in pr_rows if row["error"]],
        "ci": [row["id"] for row in ci_rows if row["error"]],
    }

    class Noop:
        async def chat_json(self, system_prompt: str, user_payload: dict[str, Any]) -> dict[str, Any]:
            return {}

        async def chat_text(self, system_prompt: str, user_message: str) -> str:
            return ""

    def _same(left: Any, right: Any) -> bool:
        return json.dumps(left, ensure_ascii=False, sort_keys=True, default=str) == json.dumps(
            right, ensure_ascii=False, sort_keys=True, default=str
        )

    fallback_rows = {
        "issue": [
            _same(row["output"], IssueAgent(llm=Noop())._fallback_analysis(case["issue"], {}))
            for case, row in zip(ISSUE_CASES, issue_rows)
        ],
        "pr": [
            _same(
                row["output"],
                PRReviewAgent(llm=Noop())._fallback_review(case["pr"], {}, chunk_pr_files(case["pr"]["files"])),
            )
            for case, row in zip(PR_CASES, pr_rows)
        ],
        "ci": [
            _same(row["output"], CIDebugAgent(llm=Noop())._fallback_debug(case["workflow_run"], {}))
            for case, row in zip(CI_CASES, ci_rows)
        ],
    }
    attempts_by_case: dict[str, int] = {}
    for call in llm.calls:
        if call.get("purpose") in {"issue_agent", "pr_review_agent", "ci_debug_agent"}:
            attempts_by_case[call.get("case_id", "-")] = attempts_by_case.get(call.get("case_id", "-"), 0) + 1
    retry_cases = sorted(case_id for case_id, count in attempts_by_case.items() if count > 1)
    finish_reasons = {
        reason: sum(1 for call in llm.calls if call.get("finish_reason") == reason)
        for reason in sorted({str(call.get("finish_reason")) for call in llm.calls})
    }

    payload = {
        "experiment": "exp02_specialized_agents",
        "model": llm.model,
        "sample_sizes": {"issue": len(issue_rows), "pr": len(pr_rows), "ci": len(ci_rows)},
        "dataset_note": "Synthetic labeled benchmark authored for this experiment; not human-labeled production data.",
        "schema_repair_note": "A schema-repair LLM call is used only when the first structured output fails Pydantic validation; substantive content is preserved.",
        "elapsed_seconds": elapsed,
        "usage": {
            **llm.totals(),
            "schema_normalizations": llm.normalizations,
            "parse_retries": llm.retries,
        },
        "retry_cases": retry_cases,
        "finish_reasons": finish_reasons,
        "fallback_counts": {group: sum(flags) for group, flags in fallback_rows.items()},
        "fallback_flags": fallback_rows,
        "metrics": {"issue": issue_metrics, "pr": pr_metrics, "ci": ci_metrics},
        "mean_elapsed_ms": {
            "issue": mean([row["elapsed_ms"] for row in issue_rows]),
            "pr": mean([row["elapsed_ms"] for row in pr_rows]),
            "ci": mean([row["elapsed_ms"] for row in ci_rows]),
        },
        "errors": errors,
        "rows": {"issue": issue_rows, "pr": pr_rows, "ci": ci_rows},
        "llm_calls": llm.calls,
    }
    path = write_json("exp02_results.json", payload)
    print(json.dumps({key: payload[key] for key in ("sample_sizes", "elapsed_seconds", "usage", "metrics", "mean_elapsed_ms", "errors")}, ensure_ascii=False, indent=2))
    print(f"saved: {path}")


if __name__ == "__main__":
    asyncio.run(main())

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from common import CASE_ID, MAX_TOKENS, PURPOSE, REPAIR_SCHEMA, RecordingLLM, mean, print_table, pstdev, write_json
from datasets import CI_CASES, ISSUE_CASES, PR_CASES

from app.schemas.analysis import CIDebugOutput, IssueAnalysisOutput, PRReviewOutput
from app.schemas.workflow import WorkflowSpec, WorkflowTask, WorkflowTaskResult
from app.services.agents.ci_debug_agent import CIDebugAgent
from app.services.agents.issue_agent import IssueAgent
from app.services.agents.planner_agent import PlannerAgent
from app.services.agents.pr_review_agent import PRReviewAgent
from app.services.agents.workflow_orchestrator import WorkflowOrchestrator

BUNDLES = [
    {"bundle_id": f"bundle-{index + 1:02d}", "issue": ISSUE_CASES[index], "pr": PR_CASES[index], "ci": CI_CASES[index]}
    for index in range(10)
]
MESSAGE = "请综合分析当前 Issue、PR 和失败的 CI，并给出分诊、审查和排障结论。"

SINGLE_SYSTEM = """你是 DevFlow AI 的单体工程分析 Agent。
输入包含一个 GitHub Issue、一个 Pull Request 和一个失败的 CI run。
只返回一个 JSON 对象，字段必须为：
{
  "issue_category": "Bug|Feature|Documentation|Test|Ops|Refactor|Question",
  "pr_has_bug": true 或 false,
  "pr_bug_reason": "简述是否存在明确缺陷",
  "ci_root_cause": "简述 CI 失败根因"
}
不要输出 JSON 以外的任何内容。"""


def _workflow_context(bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "has_repo": False,
        "has_issue": True,
        "issue_id": str(uuid.uuid4()),
        "issue_number": bundle["issue"]["issue"]["number"],
        "has_pr": True,
        "pr_id": str(uuid.uuid4()),
        "pr_number": bundle["pr"]["pr"]["number"],
        "has_ci_run": True,
        "workflow_run_id": str(uuid.uuid4()),
        "workflow_run_number": bundle["ci"]["workflow_run"]["github_run_id"],
        "disable_replan": True,
        "workflow_task_timeout_seconds": 420,
        "issue_payload": bundle["issue"]["issue"],
        "pr_payload": bundle["pr"]["pr"],
        "ci_payload": bundle["ci"]["workflow_run"],
    }


def _normalize_category(value: Any) -> str:
    text = str(value or "").strip().lower()
    mapping = {
        "bug": "Bug",
        "feature": "Feature",
        "documentation": "Documentation",
        "docs": "Documentation",
        "test": "Test",
        "tests": "Test",
        "ops": "Ops",
        "operations": "Ops",
        "refactor": "Refactor",
        "question": "Question",
    }
    return mapping.get(text, str(value or "").strip())


def _normalize_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1", "是", "有", "存在", "has bug", "buggy"}:
            return True
        if lowered in {"false", "no", "0", "否", "没有", "不存在", "clean", "ok"}:
            return False
    return None


def _evaluate_subtasks(issue_category: str | None, pr_has_bug: bool | None, ci_root_cause: str | None, bundle: dict[str, Any]) -> dict[str, Any]:
    issue_ok = _normalize_category(issue_category) == bundle["issue"]["expected_category"]
    normalized_pr = _normalize_bool(pr_has_bug)
    pr_ok = normalized_pr is not None and normalized_pr == bool(bundle["pr"]["has_bug"])
    ci_text = str(ci_root_cause or "").lower()
    ci_ok = any(keyword.lower() in ci_text for keyword in bundle["ci"]["expected_root_keywords"])
    correct = sum([issue_ok, pr_ok, ci_ok])
    return {
        "issue_correct": issue_ok,
        "pr_correct": pr_ok,
        "ci_correct": ci_ok,
        "correct_subtasks": correct,
        "completion_rate": round(correct / 3, 4),
        "full_success": correct == 3,
    }


async def run_single(bundle: dict[str, Any]) -> dict[str, Any]:
    llm = RecordingLLM(concurrency=4)
    CASE_ID.set(bundle["bundle_id"])
    PURPOSE.set("single_agent")
    MAX_TOKENS.set(1200)
    started = time.perf_counter()
    payload = {
        "issue": bundle["issue"]["issue"],
        "pull_request": bundle["pr"]["pr"],
        "workflow_run": bundle["ci"]["workflow_run"],
    }
    output: dict[str, Any] = {}
    error = None
    try:
        output = await llm.chat_json(SINGLE_SYSTEM, payload)
        if not output:
            output = await llm.chat_json(SINGLE_SYSTEM + "\n上一次输出不是合法 JSON，请重试。", payload)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    evaluation = _evaluate_subtasks(
        output.get("issue_category"),
        output.get("pr_has_bug"),
        output.get("ci_root_cause"),
        bundle,
    )
    return {
        "mode": "A_single",
        "bundle_id": bundle["bundle_id"],
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "usage": llm.totals(),
        "evaluation": evaluation,
        "output": output,
        "error": error,
    }


def _runners(llm: RecordingLLM) -> dict[str, Any]:
    async def run_issue(task: WorkflowTask, spec: WorkflowSpec, context: dict[str, Any]) -> WorkflowTaskResult:
        REPAIR_SCHEMA.set(IssueAnalysisOutput)
        output = await IssueAgent(llm=llm).run(context["issue_payload"], {})
        return WorkflowTaskResult(
            task_id=task.id,
            agent_name=task.agent_name,
            task_type=task.task_type,
            status="success",
            summary=str(output.get("summary") or ""),
            output=output,
            confidence=output.get("confidence"),
            evidence_count=len(output.get("evidence") or []),
        )

    async def run_pr(task: WorkflowTask, spec: WorkflowSpec, context: dict[str, Any]) -> WorkflowTaskResult:
        REPAIR_SCHEMA.set(PRReviewOutput)
        output = await PRReviewAgent(llm=llm).run(context["pr_payload"], {})
        return WorkflowTaskResult(
            task_id=task.id,
            agent_name=task.agent_name,
            task_type=task.task_type,
            status="success",
            summary=str(output.get("summary") or ""),
            output=output,
            confidence=output.get("confidence"),
            evidence_count=len(output.get("review_findings") or []),
        )

    async def run_ci(task: WorkflowTask, spec: WorkflowSpec, context: dict[str, Any]) -> WorkflowTaskResult:
        REPAIR_SCHEMA.set(CIDebugOutput)
        output = await CIDebugAgent(llm=llm).run(context["ci_payload"], {})
        return WorkflowTaskResult(
            task_id=task.id,
            agent_name=task.agent_name,
            task_type=task.task_type,
            status="success",
            summary=str(output.get("failure_summary") or ""),
            output=output,
            confidence=output.get("confidence"),
            evidence_count=len(output.get("related_files") or []),
        )

    return {"issue_analysis": run_issue, "pr_review": run_pr, "ci_debug": run_ci}


async def run_workflow(bundle: dict[str, Any], mode: str) -> dict[str, Any]:
    llm = RecordingLLM(concurrency=4)
    CASE_ID.set(bundle["bundle_id"])
    PURPOSE.set(mode)
    MAX_TOKENS.set(3000)
    context = _workflow_context(bundle)
    started = time.perf_counter()
    error = None
    report: dict[str, Any] = {}
    try:
        spec_data = await PlannerAgent().run({"message": MESSAGE}, context)
        spec = WorkflowSpec.model_validate(spec_data)
        spec.max_parallel_tasks = 1 if mode == "B_serial" else 3
        orchestrator = WorkflowOrchestrator(_runners(llm))
        report = await orchestrator.run_spec(spec, context, allow_replan=False)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    results = report.get("task_results") or []
    by_type = {str(item.get("task_type")): item.get("output") or {} for item in results if isinstance(item, dict)}
    issue_output = by_type.get("issue_analysis") or {}
    pr_output = by_type.get("pr_review") or {}
    ci_output = by_type.get("ci_debug") or {}
    pr_findings = pr_output.get("review_findings") or []
    finding_text = "\n".join(
        " ".join(str(item.get(key) or "") for key in ("title", "evidence", "required_action"))
        for item in pr_findings
        if isinstance(item, dict)
    ) + "\n" + "\n".join(str(item) for item in pr_output.get("blocking_issues") or [])
    pr_has_bug = None
    if bundle["pr"]["has_bug"]:
        pr_has_bug = any(keyword.lower() in finding_text.lower() for keyword in bundle["pr"]["bug_keywords"])
    else:
        pr_has_bug = False
    evaluation = _evaluate_subtasks(
        issue_output.get("category"),
        pr_has_bug,
        ci_output.get("root_cause"),
        bundle,
    )
    task_statuses = [str(item.get("status")) for item in results if isinstance(item, dict)]
    return {
        "mode": mode,
        "bundle_id": bundle["bundle_id"],
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "usage": llm.totals(),
        "evaluation": evaluation,
        "planner_task_count": len(spec.tasks) if "spec" in locals() else None,
        "task_statuses": task_statuses,
        "workflow_metrics": report.get("metrics") or {},
        "error": error,
    }


async def main() -> None:
    started = time.perf_counter()
    gate = asyncio.Semaphore(3)

    async def guarded(coro):
        async with gate:
            return await coro

    tasks = []
    for bundle in BUNDLES:
        tasks.append(guarded(run_single(bundle)))
        tasks.append(guarded(run_workflow(bundle, "B_serial")))
        tasks.append(guarded(run_workflow(bundle, "C_parallel")))
    rows: list[dict[str, Any]] = await asyncio.gather(*tasks)
    elapsed = round(time.perf_counter() - started, 2)

    summary_rows = []
    for mode in ("A_single", "B_serial", "C_parallel"):
        group = [row for row in rows if row["mode"] == mode]
        summary_rows.append(
            {
                "mode": mode,
                "n": len(group),
                "avg_latency_ms": mean([row["elapsed_ms"] for row in group]),
                "std_latency_ms": pstdev([row["elapsed_ms"] for row in group]),
                "avg_tokens": mean([float(row["usage"]["total_tokens"]) for row in group]),
                "avg_calls": mean([float(row["usage"]["calls"]) for row in group]),
                "completion_rate": mean([row["evaluation"]["completion_rate"] for row in group]),
                "full_success_rate": mean([1.0 if row["evaluation"]["full_success"] else 0.0 for row in group]),
                "errors": sum(1 for row in group if row["error"]),
            }
        )
    by_mode = {row["mode"]: row for row in summary_rows}
    speedups = {
        "B_over_A_latency": round(by_mode["A_single"]["avg_latency_ms"] / max(by_mode["B_serial"]["avg_latency_ms"], 0.001), 3),
        "C_over_B_speedup": round(by_mode["B_serial"]["avg_latency_ms"] / max(by_mode["C_parallel"]["avg_latency_ms"], 0.001), 3),
        "C_over_A_latency": round(by_mode["A_single"]["avg_latency_ms"] / max(by_mode["C_parallel"]["avg_latency_ms"], 0.001), 3),
        "C_vs_B_token_delta": by_mode["C_parallel"]["avg_tokens"] - by_mode["B_serial"]["avg_tokens"],
    }
    payload = {
        "experiment": "exp01_multi_agent",
        "model": RecordingLLM().model,
        "bundle_count": len(BUNDLES),
        "elapsed_seconds": elapsed,
        "dataset_note": "10 synthetic issue/PR/CI bundles from exp02 benchmark; A=monolithic single LLM call, B/C share Planner+Observer+Synthesis and specialized agents, only max_parallel_tasks differs.",
        "summary": summary_rows,
        "speedups": speedups,
        "rows": rows,
    }
    path = write_json("exp01_results.json", payload)
    print(json.dumps({"elapsed_seconds": elapsed, "summary": summary_rows, "speedups": speedups}, ensure_ascii=False, indent=2))
    print_table(summary_rows, ["mode", "n", "avg_latency_ms", "std_latency_ms", "avg_tokens", "avg_calls", "completion_rate", "full_success_rate", "errors"])
    print(f"saved: {path}")


if __name__ == "__main__":
    asyncio.run(main())

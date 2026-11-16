from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from typing import Any

from common import CASE_ID, MAX_TOKENS, PURPOSE, RecordingLLM, mean, write_json

from app.services.context_compression import (
    COMPACT_SUMMARY_SYSTEM_PROMPT,
    build_compaction_summary_payload,
    clip_to_token_budget,
    compress_messages,
    ensure_compaction_summary_preserves_key_facts,
    estimate_tokens,
    fallback_compaction_summary,
    fallback_memory_update,
    format_compaction_summary,
    microcompact_messages,
    render_structured_memory,
    structured_memory_from_model,
)

NOISE = (
    "读取文件后得到以下无关上下文：" + ("字段说明、历史日志、配置注释。" * 60) + "\n"
)

MESSAGES: list[dict[str, Any]] = [
    {"role": "user", "content": "我们开始处理认证刷新问题。先确认工作范围。"},
    {"role": "assistant", "content": "好的。当前分支是 fix/auth-refresh，关联 PR #128，负责人是 Alice，截止时间是本周五。"},
    {"role": "tool_result", "route": "workspace.read_file", "tool_calls": [{"tool_name": "workspace.read_file"}], "content": NOISE + "关键信息：需要修改 backend/app/services/auth/middleware.py，并且 token 刷新放在 middleware，不放 route。"},
    {"role": "user", "content": "测试和运行命令是什么？"},
    {"role": "assistant", "content": "测试命令是 pytest backend/app/tests/test_auth.py -q；本地运行命令是 uvicorn app.main:app --reload。"},
    {"role": "tool_result", "route": "rag.search_similar_documents", "tool_calls": [{"tool_name": "rag.search_similar_documents"}], "content": NOISE + "历史决策：refresh token 存入 Redis，TTL 7 天；新增表 refresh_tokens，迁移文件 backend/migrations/0009_refresh_tokens.sql。"},
    {"role": "user", "content": "还有哪些待办？"},
    {"role": "assistant", "content": "待办：1. 补充过期 token 单测；2. 更新 README 环境变量。"},
    {"role": "tool_result", "route": "workspace.search_code", "tool_calls": [{"tool_name": "workspace.search_code"}], "content": NOISE + "错误线索：MissingAuthorizationHeader 出现在 backend/app/api/routes/repos.py:42，原因是 Bearer token 解析失败。"},
    {"role": "user", "content": "CI 现在什么情况？"},
    {"role": "assistant", "content": "CI 失败 job 是 pytest-auth，错误是 AssertionError: assert 500 == 401。"},
    {"role": "tool_result", "route": "workspace.read_file", "tool_calls": [{"tool_name": "workspace.read_file"}], "content": NOISE + "注意：回答使用中文，保持简洁；代码约定是不要引入新依赖。"},
    {"role": "user", "content": "再看一下认证模块的上下文。"},
    {"role": "assistant", "content": "已确认认证模块只改 middleware.py 和 test_auth.py，不调整路由层。"},
    {"role": "tool_result", "route": "rag.search_similar_documents", "tool_calls": [{"tool_name": "rag.search_similar_documents"}], "content": NOISE + "补充：用户偏好中文简洁回答；截止时间本周五；负责人 Alice。"},
    {"role": "user", "content": "继续。"},
    {"role": "assistant", "content": "下一步先复现 assert 500 == 401，再补过期 token 单测。"},
    {"role": "tool_result", "route": "workspace.read_file", "tool_calls": [{"tool_name": "workspace.read_file"}], "content": NOISE + "重复确认：Redis TTL 7 天，表 refresh_tokens，迁移 0009_refresh_tokens.sql。"},
    {"role": "user", "content": "好的。"},
    {"role": "assistant", "content": "我会保持不引入新依赖，并更新 README 环境变量说明。"},
    {"role": "tool_result", "route": "workspace.read_file", "tool_calls": [{"tool_name": "workspace.read_file"}], "content": NOISE + "路径再次确认：backend/app/services/auth/middleware.py。"},
    {"role": "user", "content": "准备改代码。"},
    {"role": "assistant", "content": "开始修改 middleware.py，然后运行 pytest backend/app/tests/test_auth.py -q。"},
    {"role": "user", "content": "最后请总结当前任务：需要修改哪些文件、运行什么命令、有哪些决策和待办？"},
]

FACTS: list[dict[str, Any]] = [
    {"id": "middleware_file", "keywords": ["backend/app/services/auth/middleware.py"]},
    {"id": "test_file", "keywords": ["test_auth.py"]},
    {"id": "test_command", "keywords": ["pytest backend/app/tests/test_auth.py"]},
    {"id": "run_command", "keywords": ["uvicorn app.main:app --reload"]},
    {"id": "refresh_location", "keywords": ["不放 route"]},
    {"id": "redis_ttl", "keywords": ["redis", "7 天"]},
    {"id": "todo_test", "keywords": ["过期 token 单测"]},
    {"id": "todo_readme", "keywords": ["readme 环境变量"]},
    {"id": "error_file", "keywords": ["repos.py:42"]},
    {"id": "error_reason", "keywords": ["bearer", "解析失败"]},
    {"id": "preference", "keywords": ["中文", "简洁"]},
    {"id": "branch", "keywords": ["fix/auth-refresh"]},
    {"id": "pr", "keywords": ["#128"]},
    {"id": "table", "keywords": ["refresh_tokens"]},
    {"id": "migration", "keywords": ["0009_refresh_tokens.sql"]},
    {"id": "ci_job", "keywords": ["pytest-auth"]},
    {"id": "ci_error", "keywords": ["assert 500 == 401"]},
    {"id": "convention", "keywords": ["不要引入新依赖"]},
    {"id": "deadline", "keywords": ["本周五"]},
    {"id": "owner", "keywords": ["alice"]},
]

QUESTIONS: list[dict[str, Any]] = [
    {"id": "q1", "question": "需要修改哪个 middleware 文件？", "keywords": ["middleware.py"], "match_all": False},
    {"id": "q2", "question": "测试命令是什么？", "keywords": ["pytest", "test_auth.py"], "match_all": True},
    {"id": "q3", "question": "token 刷新逻辑放在哪里？", "keywords": ["middleware", "不放 route"], "match_all": False},
    {"id": "q4", "question": "refresh token 用什么存储、TTL 多久？", "keywords": ["redis", "7 天"], "match_all": False},
    {"id": "q5", "question": "有哪些待办事项？", "keywords": ["过期 token 单测", "readme"], "match_all": True},
    {"id": "q6", "question": "MissingAuthorizationHeader 出现在哪个文件？", "keywords": ["repos.py:42"], "match_all": False},
    {"id": "q7", "question": "当前分支名和 PR 编号？", "keywords": ["fix/auth-refresh", "#128"], "match_all": True},
    {"id": "q8", "question": "新增的数据库表和迁移文件是什么？", "keywords": ["refresh_tokens", "0009_refresh_tokens.sql"], "match_all": True},
    {"id": "q9", "question": "CI 失败的 job 和错误是什么？", "keywords": ["pytest-auth", "500 == 401"], "match_all": True},
    {"id": "q10", "question": "用户对回答语言有什么偏好？", "keywords": ["中文"], "match_all": False},
    {"id": "q11", "question": "代码约定是什么？", "keywords": ["不要引入新依赖"], "match_all": False},
    {"id": "q12", "question": "截止时间和负责人是谁？", "keywords": ["本周五", "alice"], "match_all": True},
]

ANSWER_SYSTEM = """你是一个严格依据上下文回答问题的工程助手。
只能使用用户消息中 <context> 与 </context> 之间的信息。
如果上下文里没有答案，回答“不知道”。回答尽量简短，直接给出关键事实。"""

MEMORY_SYSTEM = """请从对话中提取结构化记忆，只返回 JSON：
{"summary": "...", "facts": ["..."], "decisions": ["..."], "open_questions": ["..."], "tasks": ["..."], "user_preferences": ["..."], "repo_context": ["..."]}
必须保留文件路径、命令、错误信息、决策和待办的原文。"""


def _render(messages: list[dict[str, Any]], *, limit: int | None = None) -> str:
    lines = [f"{item['role']}: {item['content']}" for item in messages]
    text = "\n\n".join(lines)
    return clip_to_token_budget(text, limit) if limit else text


def _simple_truncate(messages: list[dict[str, Any]], max_tokens: int) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    used = 0
    for message in reversed(messages):
        cost = estimate_tokens(str(message.get("content") or ""))
        if kept and used + cost > max_tokens:
            break
        kept.append(message)
        used += cost
    return list(reversed(kept))


def _retention(text: str) -> dict[str, Any]:
    lower = text.lower()
    kept = [fact["id"] for fact in FACTS if any(keyword.lower() in lower for keyword in fact["keywords"])]
    missing = [fact["id"] for fact in FACTS if fact["id"] not in kept]
    return {"kept": len(kept), "total": len(FACTS), "rate": round(len(kept) / len(FACTS), 4), "missing": missing}


def _score_answer(answer: str, question: dict[str, Any]) -> bool:
    lower = answer.lower()
    hits = [keyword.lower() in lower for keyword in question["keywords"]]
    return all(hits) if question["match_all"] else any(hits)


async def _build_mode_c(llm: RecordingLLM, query: str) -> tuple[str, dict[str, Any]]:
    CASE_ID.set("compression")
    PURPOSE.set("compression_summary")
    MAX_TOKENS.set(2000)
    started = time.perf_counter()
    micro, micro_stats = microcompact_messages(MESSAGES, query, keep_recent=6, max_excerpt_tokens=80)
    payload = build_compaction_summary_payload(micro, max_tokens=5000)
    llm_summary = ""
    try:
        llm_summary = await llm.chat_text(
            COMPACT_SUMMARY_SYSTEM_PROMPT,
            f"当前请求：{query}\n\n需要压缩的对话片段：\n{payload}",
        )
    except Exception:  # noqa: BLE001
        llm_summary = ""
    summary = format_compaction_summary(llm_summary)
    summary_mode = "llm"
    if not summary and llm_summary.strip():
        summary = clip_to_token_budget(llm_summary, 900)
        summary_mode = "llm_raw"
    if not summary:
        summary = fallback_compaction_summary(micro, max_tokens=900)
        summary_mode = "fallback_extractive"
    summary, preservation = ensure_compaction_summary_preserves_key_facts(micro, summary, 1200)

    PURPOSE.set("structured_memory")
    memory = {}
    try:
        memory = await llm.chat_json(MEMORY_SYSTEM, {"conversation": payload[:12000]})
    except Exception:  # noqa: BLE001
        memory = {}
    memory = structured_memory_from_model(memory) if memory else {}
    if not memory.get("summary") and not memory.get("facts"):
        memory = fallback_memory_update(payload, "", "direct_answer", [])
        memory_mode = "fallback_extractive"
    else:
        memory_mode = "llm"
    memory_text = render_structured_memory(SimpleNamespace(**memory), max_tokens=650)

    recent, history_stats = compress_messages(micro, max_tokens=550)
    recent_text = "\n\n".join(f"{item['role']}: {item['content']}" for item in recent)
    summary_text = clip_to_token_budget(summary, 650)
    context = "\n\n".join(
        [
            "[Compaction Summary]\n" + summary_text,
            "[Structured Memory]\n" + memory_text,
            "[Recent Messages]\n" + recent_text,
        ]
    )
    context = clip_to_token_budget(context, 1400)
    return context, {
        "microcompact": micro_stats,
        "history_compression": history_stats,
        "summary_mode": summary_mode,
        "memory_mode": memory_mode,
        "preservation": preservation,
        "compression_elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
    }


async def _ask(llm: RecordingLLM, mode: str, context: str, question: str, *, task: bool = False) -> dict[str, Any]:
    CASE_ID.set(f"{mode}:{question[:24]}")
    PURPOSE.set("answer")
    MAX_TOKENS.set(500 if not task else 700)
    started = time.perf_counter()
    try:
        answer = await llm.chat_text(ANSWER_SYSTEM, f"<context>\n{context}\n</context>\n\n问题：{question}")
        if not answer.strip():
            answer = await llm.chat_text(
                ANSWER_SYSTEM,
                f"<context>\n{context}\n</context>\n\n问题：{question}\n请直接给出关键事实，不要解释，不要输出空内容。",
            )
        return {
            "mode": mode,
            "question": question,
            "answer": answer,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "mode": mode,
            "question": question,
            "answer": "",
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _task_completion(answer: str) -> dict[str, Any]:
    lower = answer.lower()
    categories = {
        "files": "middleware.py" in lower and "test_auth.py" in lower,
        "commands": "pytest" in lower,
        "decisions": "redis" in lower and ("middleware" in lower or "不放 route" in lower),
        "todos": "过期" in lower and "readme" in lower,
    }
    return {
        "categories": categories,
        "completed": sum(1 for value in categories.values() if value),
        "rate": round(sum(1 for value in categories.values() if value) / 4, 4),
    }


async def main() -> None:
    query = "请总结当前任务：需要修改哪些文件、运行什么命令、有哪些决策和待办？"
    llm = RecordingLLM(concurrency=6)
    started = time.perf_counter()

    contexts: dict[str, str] = {
        "A_none": _render(MESSAGES),
        "B_truncate": _render(_simple_truncate(MESSAGES, 1200)),
    }
    context_c, compression_stats = await _build_mode_c(llm, query)
    contexts["C_full"] = context_c

    context_tokens = {mode: estimate_tokens(text) for mode, text in contexts.items()}
    retention = {mode: _retention(text) for mode, text in contexts.items()}

    requests = []
    for mode, context in contexts.items():
        for question in QUESTIONS:
            requests.append(_ask(llm, mode, context, question["question"]))
        requests.append(_ask(llm, mode, context, "请完成最终任务：列出需要修改的文件、测试命令、已确定的决策和待办事项。", task=True))
    answers = await asyncio.gather(*requests)

    answer_by_mode: dict[str, list[dict[str, Any]]] = {mode: [] for mode in contexts}
    task_by_mode: dict[str, dict[str, Any]] = {}
    for item in answers:
        if item["question"].startswith("请完成最终任务"):
            task_by_mode[item["mode"]] = {**item, "completion": _task_completion(item["answer"])}
        else:
            answer_by_mode[item["mode"]].append(item)

    scoring: dict[str, Any] = {}
    for mode in contexts:
        rows = []
        for question, answer in zip(QUESTIONS, answer_by_mode[mode]):
            rows.append(
                {
                    "id": question["id"],
                    "hit": _score_answer(answer["answer"], question),
                    "answer": answer["answer"],
                    "error": answer["error"],
                }
            )
        scoring[mode] = {
            "accuracy": round(sum(1 for row in rows if row["hit"]) / len(rows), 4),
            "rows": rows,
            "task_completion": task_by_mode.get(mode, {}).get("completion", {}),
        }

    consistency = []
    a_rows = {row["id"]: row for row in scoring["A_none"]["rows"]}
    c_rows = {row["id"]: row for row in scoring["C_full"]["rows"]}
    for question_id, a_row in a_rows.items():
        c_row = c_rows[question_id]
        consistency.append(a_row["hit"] == c_row["hit"])
    consistency_rate = round(sum(consistency) / len(consistency), 4)

    baseline_tokens = context_tokens["A_none"] or 1
    summary = []
    for mode in ("A_none", "B_truncate", "C_full"):
        summary.append(
            {
                "mode": mode,
                "context_tokens": context_tokens[mode],
                "token_saving_vs_A": round(1 - context_tokens[mode] / baseline_tokens, 4),
                "fact_retention": retention[mode]["rate"],
                "qa_accuracy": scoring[mode]["accuracy"],
                "task_completion": scoring[mode]["task_completion"].get("rate", 0.0),
            }
        )

    payload = {
        "experiment": "exp04_context_compression",
        "model": llm.model,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "usage": llm.totals(),
        "context_tokens": context_tokens,
        "retention": retention,
        "compression_stats": compression_stats,
        "summary": summary,
        "answer_consistency_A_vs_C": consistency_rate,
        "scoring": scoring,
        "task_answers": {mode: {key: value for key, value in item.items() if key != "completion"} for mode, item in task_by_mode.items()},
        "llm_calls": llm.calls,
    }
    path = write_json("exp04_results.json", payload)
    print(json.dumps({"summary": summary, "answer_consistency_A_vs_C": consistency_rate, "retention": retention, "compression_stats": compression_stats, "usage": payload["usage"]}, ensure_ascii=False, indent=2))
    print(f"saved: {path}")


if __name__ == "__main__":
    asyncio.run(main())

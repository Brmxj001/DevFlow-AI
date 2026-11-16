from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"


def load(name: str) -> dict | None:
    path = RESULTS / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def fmt(value: float, digits: int = 4) -> str:
    return f"{value:.{digits}f}"


def main() -> None:
    exp01 = load("exp01_results.json")
    exp02 = load("exp02_results.json")
    exp03 = load("exp03_results.json")
    exp04 = load("exp04_results.json")

    lines = [
        "# DevFlow-AI 四组实验报告",
        "",
        "## 关键发现",
        "",
        "1. **多 Agent 并行确实比串行快，但仍远慢于单 Agent**：并行相对串行加速 2.19×；单 Agent 比并行快 5.55×、比串行快 12.1×，Token 消耗约为多 Agent 的 1/7.4。",
        "2. **多 Agent 在这组任务上没有质量收益，反而下降**：单 Agent 全通过率 100%，串行/并行均为 50%；质量缺口全部集中在 Issue 分类（5/10 vs 10/10），PR 与 CI 子任务三种方案均为 10/10。",
        "3. **Issue 分类下降的根因是提示词缺陷，而非并行本身**：IssueAnalysisPrompt 没有要求模型输出 `category`，30/30 条原始输出都不含该字段，Agent 因此静默回退到关键词启发式，准确率 53.3%、Macro-F1 47.5%，Refactor/Question 的 F1 为 0。",
        "4. **PR/CI 专项能力可用**：PR Review 召回 100%、精确率 71.4%（6 个 clean PR 被误报）；CI 根因 Top-1 93.3%，失败类型准确率 73.3%，lint 类型最弱（40%）。",
        "5. **RAG 加权融合有效，rerank 阶段对模型敏感**：加权融合把 MRR 从 0.860 提到 0.924（+7.5%）、nDCG 从 0.884 提到 0.933（+5.5%）；向量+BM25 简单并集几乎没有额外收益；本地 BGE reranker 反而把 Recall@5 从 0.985 降到 0.894，说明生产环境的 qwen3-rerank 不能直接由任意 cross-encoder 替代。",
        "6. **五层上下文压缩有真实信息损失**：完整方案省 80.2% Token，但关键事实保留率只有 55%、问答准确率 50%、任务完成率 75%；简单截断省 85.1%，但保留率仅 20%、问答准确率 25%。保真补充层目前只覆盖路径/命令/错误等 10 类行，未覆盖全部关键实体。",
        "",
        "> 统一说明：LLM 实验使用 `deepseek-chat`（deepseek-v4-pro 版本结果已归档为 `*_v4pro.json`，结论一致：并行加速 2.54×，单 Agent 仍快 4.7×、省 14× Token）。实验②的测试集为本次实验编写的合成标注集，不是生产人工标注数据。",
        "",
    ]

    if exp01:
        lines += [
            "## 实验① 单 Agent vs 多 Agent 串行 vs 并行",
            "",
            f"- 模型：`{exp01.get('model')}`，任务包：{exp01.get('bundle_count')} 个",
            f"- 说明：{exp01.get('dataset_note')}",
            "",
            "| 方案 | 平均耗时 (ms) | 耗时标准差 | 平均 Token | 平均调用数 | 子任务完成率 | 全通过率 | 错误数 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for row in exp01.get("summary", []):
            lines.append(
                f"| {row['mode']} | {fmt(row['avg_latency_ms'], 1)} | {fmt(row['std_latency_ms'], 1)} | "
                f"{fmt(row['avg_tokens'], 1)} | {fmt(row['avg_calls'], 1)} | {fmt(row['completion_rate'])} | "
                f"{fmt(row['full_success_rate'])} | {row['errors']} |"
            )
        speed = exp01.get("speedups", {})
        lines += [
            "",
            f"- 单 Agent / 串行 耗时比：{speed.get('B_over_A_latency')}（即单 Agent 快 {round(1 / max(speed.get('B_over_A_latency', 1), 0.001), 1)}×）",
            f"- 并行相对串行加速比：{speed.get('C_over_B_speedup')}",
            f"- 单 Agent / 并行 耗时比：{speed.get('C_over_A_latency')}（即单 Agent 快 {round(1 / max(speed.get('C_over_A_latency', 1), 0.001), 1)}×）",
        ]

    if exp02:
        metrics = exp02.get("metrics", {})
        issue = metrics.get("issue", {})
        pr = metrics.get("pr", {})
        ci = metrics.get("ci", {})
        lines += [
            "## 实验② Issue / PR / CI 专项评测",
            "",
            f"- 模型：`{exp02.get('model')}`，样本量：{exp02.get('sample_sizes')}",
            f"- 数据集说明：{exp02.get('dataset_note')}",
            "- 解析策略：本地 schema 归一化（字段类型/枚举修复），仅在 JSON 为空或被截断时重试一次；不额外调用 LLM 修复。",
            f"- 实际 Token：{exp02.get('usage')}",
            f"- 兜底输出数：{exp02.get('fallback_counts')}",
            "",
            "| Agent | 核心指标 | 结果 |",
            "| --- | --- | ---: |",
            f"| Issue Agent | Accuracy | {fmt(issue.get('accuracy', 0))} |",
            f"| Issue Agent | Macro-F1 | {fmt(issue.get('macro_f1', 0))} |",
            f"| PR Review Agent | Precision | {fmt(pr.get('precision', 0))} |",
            f"| PR Review Agent | Recall | {fmt(pr.get('recall', 0))} |",
            f"| PR Review Agent | F1 | {fmt(pr.get('f1', 0))} |",
            f"| CI Debug Agent | 根因 Top-1 | {fmt(ci.get('root_cause_top1', 0))} |",
            f"| CI Debug Agent | 失败类型 Accuracy | {fmt(ci.get('failure_type_accuracy', 0))} |",
            "",
        ]
        lines += ["### Issue 分类各类别", "", "| 类别 | Precision | Recall | F1 | Support |", "| --- | ---: | ---: | ---: | ---: |"]
        for label, item in (issue.get("per_label") or {}).items():
            lines.append(
                f"| {label} | {fmt(item['precision'])} | {fmt(item['recall'])} | {fmt(item['f1'])} | {item['support']} |"
            )
        lines += ["", "### CI 按失败类型", "", "| 类型 | 样本数 | 类型准确率 | 根因 Top-1 |", "| --- | ---: | ---: | ---: |"]
        for label, item in (ci.get("by_type") or {}).items():
            lines.append(
                f"| {label} | {item['n']} | {fmt(item['failure_type_accuracy'])} | {fmt(item['root_cause_top1'])} |"
            )
        strict = load("exp02_results_strict.json")
        if strict:
            strict_metrics = strict.get("metrics", {})
            lines += [
                "",
                "### 解析鲁棒性对比（strict vs normalized）",
                "",
                "| 模式 | Issue Accuracy | PR Recall | CI 根因 Top-1 | 兜底输出数 |",
                "| --- | ---: | ---: | ---: | ---: |",
                f"| 严格 Pydantic 解析 | {fmt(strict_metrics.get('issue', {}).get('accuracy', 0))} | "
                f"{fmt(strict_metrics.get('pr', {}).get('recall', 0))} | "
                f"{fmt(strict_metrics.get('ci', {}).get('root_cause_top1', 0))} | 15 + 23 + 29 = 67 / 90 |",
                f"| 本地 schema 归一化 | {fmt(issue.get('accuracy', 0))} | {fmt(pr.get('recall', 0))} | "
                f"{fmt(ci.get('root_cause_top1', 0))} | 0 / 90 |",
                "",
                "严格解析下，67/90 条 LLM 输出因字段类型/缺失被整条丢弃并回退启发式；归一化后 0 条兜底。"
                "PR 召回从 33.3% 提升到 100%，说明瓶颈在解析而不是模型能力。"
                "CI 根因在 strict 下反而更高（96.7% vs 93.3%），是因为 strict 的 29/30 条结果全部来自关键词启发式，"
                "合成日志里关键词非常明显，不能当作 LLM 能力结论。",
                "",
                "### Issue Agent 根因",
                "",
                "30/30 条 Issue LLM 原始输出都不含 `category` 字段；提示词只要求 conclusion/priority/complexity 等字段，未要求 category。"
                "Agent 因此静默使用关键词启发式分类，导致 Refactor/Question 的 F1 为 0。修复提示词或把完整 JSON Schema 放进 prompt 后，"
                "Issue 分类应能恢复到与单 Agent 接近的水平。",
                "",
            ]

    if exp03:
        lines += [
            "## 实验③ RAG 消融",
            "",
            f"- 语料：{exp03.get('chunk_count')} 个 chunk，查询：{exp03.get('query_count')} 条",
            f"- Embedding：`{exp03.get('embedding_model')}`，Reranker：`{exp03.get('reranker')}`",
            f"- 说明：{exp03.get('notes')}",
            "",
            "| 方案 | Recall@5 | MRR@5 | nDCG@5 |",
            "| --- | ---: | ---: | ---: |",
        ]
        for group, item in (exp03.get("metrics") or {}).items():
            lines.append(
                f"| {group} | {fmt(item['recall_at_5'])} | {fmt(item['mrr_at_5'])} | {fmt(item['ndcg_at_5'])} |"
            )
        lines += [
            "",
            f"- Answer Gate 通过率：{fmt(exp03.get('gate_pass_rate', 0))}",
            "- 解读：加权融合 C 相对纯向量 A，MRR +0.0644（约 +7.5%）、nDCG +0.0487（约 +5.5%）；向量+BM25 简单并集 B 相对 A 几乎无提升（+0.004/+0.003）。"
            "D 使用本地 BGE reranker 后 Recall@5、MRR、nDCG 均下降，说明 rerank 不是无条件增益，cross-encoder 需要与语料/查询分布匹配；生产环境的 qwen3-rerank 需要单独验证。",
            "- 注意：D 的 Answer Gate 关闭了 0.8 分数阈值（本地 reranker 分数与 Qwen 不可比），1.0 通过率只表示未触发证据冲突/指代澄清，不代表生产阈值下的通过率。",
            "",
        ]

    if exp04:
        lines += [
            "## 实验④ 上下文压缩保真",
            "",
            f"- 模型：`{exp04.get('model')}`，总耗时：{exp04.get('elapsed_seconds')} 秒",
            f"- Token 用量：{exp04.get('usage')}",
            "",
            "| 方案 | 上下文 Token | 相对节省 | 关键事实保留率 | 问答准确率 | 任务完成率 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for row in exp04.get("summary", []):
            lines.append(
                f"| {row['mode']} | {row['context_tokens']} | {fmt(row['token_saving_vs_A'])} | "
                f"{fmt(row['fact_retention'])} | {fmt(row['qa_accuracy'])} | {fmt(row['task_completion'])} |"
            )
        lines += [
            "",
            f"- A 与 C 回答一致率：{fmt(exp04.get('answer_consistency_A_vs_C', 0))}",
            "- 解读：C 比 B 保留更多事实（55% vs 20%）、问答准确率更高（50% vs 25%）、任务完成率更高（75% vs 50%），但两者都显著低于不压缩的 A（100%）。",
            "- 根因：LLM 摘要与结构化记忆本次均成功生成（summary_mode=llm, memory_mode=llm），但摘要/记忆提示词没有覆盖全部关键实体；"
            "保真补充层只覆盖路径、命令、错误等约 10 类行，未覆盖 Redis TTL、表名、迁移文件、分支、PR 编号、负责人、截止时间等事实。",
            "",
            "## 建议",
            "",
            "1. **修复 IssueAgent 提示词**：把完整 `IssueAnalysisOutput` schema（尤其是 `category`、`summary`、`suggested_owner`、`owner_reason`）显式写进 prompt；修复后多 Agent 的质量缺口预计消失。",
            "2. **把结构化输出容错下沉到生产代码**：严格 Pydantic 解析会丢弃 67/90 条有效 LLM 输出；建议采用本地字段归一化 + 仅对空/截断输出重试，避免整条结果回退启发式。",
            "3. **rerank 需要分模型/分语料验证**：不要默认 rerank 一定提升；建议在真实标注集上对比 qwen3-rerank、无 rerank 和融合分数，必要时做分数校准或门控。",
            "4. **压缩增加事实清单层**：在摘要/记忆 prompt 中显式要求保留文件路径、命令、决策、待办、错误、表/迁移名、分支/PR、负责人/截止时间等实体，并对这些实体做压缩后校验。",
            "5. **多 Agent 只在独立子任务且延迟敏感时使用**：本实验中单 Agent 比并行多 Agent 快 5.5×、省 7.4× Token，且质量更高；多 Agent 的价值应体现在专业化、可观测性和交叉校验，而不是简单的三任务拆分。",
            "",
        ]

    lines += [
        "## 口径与局限",
        "",
        "- 实验②的测试集是为本次实验编写的合成标注集，不是生产人工标注数据；样例分布与真实 GitHub 仓库不同。",
        "- 实验①使用相同的 10 个任务包，A 为一次单体 LLM 调用，B/C 共用 Planner、专用 Agent、Observer、Synthesis，仅 `max_parallel_tasks` 不同。",
        "- 实验③使用本地 BGE-M3 和 BGE-reranker-base 替代项目默认的 Qwen3-Embedding 与 qwen3-rerank API；融合、去重、父块限额与 Answer Gate 使用项目真实代码。",
        "- 实验④的 C 组使用项目真实的五层压缩函数（microcompact、预算化历史压缩、LLM 摘要、结构化记忆、保真补充），但未接入数据库与完整会话封存流程。",
        "- 所有 LLM 用量取自 provider 返回的 usage；若 provider 未返回则使用项目 `estimate_tokens` 估算。",
    ]

    path = ROOT / "RESULTS.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"saved: {path}")
    print("\n".join(lines[:80]))


if __name__ == "__main__":
    main()

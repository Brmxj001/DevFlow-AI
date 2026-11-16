# DevFlow-AI 四组实验报告

## 关键发现

1. **多 Agent 并行确实比串行快，但仍远慢于单 Agent**：并行相对串行加速 2.19×；单 Agent 比并行快 5.55×、比串行快 12.1×，Token 消耗约为多 Agent 的 1/7.4。
2. **多 Agent 在这组任务上没有质量收益，反而下降**：单 Agent 全通过率 100%，串行/并行均为 50%；质量缺口全部集中在 Issue 分类（5/10 vs 10/10），PR 与 CI 子任务三种方案均为 10/10。
3. **Issue 分类下降的根因是提示词缺陷，而非并行本身**：IssueAnalysisPrompt 没有要求模型输出 `category`，30/30 条原始输出都不含该字段，Agent 因此静默回退到关键词启发式，准确率 53.3%、Macro-F1 47.5%，Refactor/Question 的 F1 为 0。
4. **PR/CI 专项能力可用**：PR Review 召回 100%、精确率 71.4%（6 个 clean PR 被误报）；CI 根因 Top-1 93.3%，失败类型准确率 73.3%，lint 类型最弱（40%）。
5. **RAG 加权融合有效，rerank 阶段对模型敏感**：加权融合把 MRR 从 0.860 提到 0.924（+7.5%）、nDCG 从 0.884 提到 0.933（+5.5%）；向量+BM25 简单并集几乎没有额外收益；本地 BGE reranker 反而把 Recall@5 从 0.985 降到 0.894，说明生产环境的 qwen3-rerank 不能直接由任意 cross-encoder 替代。
6. **五层上下文压缩有真实信息损失**：完整方案省 80.2% Token，但关键事实保留率只有 55%、问答准确率 50%、任务完成率 75%；简单截断省 85.1%，但保留率仅 20%、问答准确率 25%。保真补充层目前只覆盖路径/命令/错误等 10 类行，未覆盖全部关键实体。

> 统一说明：LLM 实验使用 `deepseek-chat`（deepseek-v4-pro 版本结果已归档为 `*_v4pro.json`，结论一致：并行加速 2.54×，单 Agent 仍快 4.7×、省 14× Token）。实验②的测试集为本次实验编写的合成标注集，不是生产人工标注数据。

## 实验① 单 Agent vs 多 Agent 串行 vs 并行

- 模型：`deepseek-chat`，任务包：10 个
- 说明：10 synthetic issue/PR/CI bundles from exp02 benchmark; A=monolithic single LLM call, B/C share Planner+Observer+Synthesis and specialized agents, only max_parallel_tasks differs.

| 方案 | 平均耗时 (ms) | 耗时标准差 | 平均 Token | 平均调用数 | 子任务完成率 | 全通过率 | 错误数 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A_single | 1505.8 | 305.6 | 584.7 | 1.0 | 1.0000 | 1.0000 | 0 |
| B_serial | 18282.3 | 1457.7 | 4412.3 | 3.0 | 0.8333 | 0.5000 | 0 |
| C_parallel | 8363.6 | 1485.9 | 4326.0 | 3.0 | 0.8333 | 0.5000 | 0 |

- 单 Agent / 串行 耗时比：0.082（即单 Agent 快 12.2×）
- 并行相对串行加速比：2.186
- 单 Agent / 并行 耗时比：0.18（即单 Agent 快 5.6×）
## 实验② Issue / PR / CI 专项评测

- 模型：`deepseek-chat`，样本量：{'issue': 30, 'pr': 30, 'ci': 30}
- 数据集说明：Synthetic labeled benchmark authored for this experiment; not human-labeled production data.
- 解析策略：本地 schema 归一化（字段类型/枚举修复），仅在 JSON 为空或被截断时重试一次；不额外调用 LLM 修复。
- 实际 Token：{'calls': 92, 'prompt_tokens': 53644, 'completion_tokens': 80080, 'total_tokens': 133724, 'errors': 0, 'schema_normalizations': 86, 'parse_retries': 2}
- 兜底输出数：{'issue': 0, 'pr': 0, 'ci': 0}

| Agent | 核心指标 | 结果 |
| --- | --- | ---: |
| Issue Agent | Accuracy | 0.5333 |
| Issue Agent | Macro-F1 | 0.4749 |
| PR Review Agent | Precision | 0.7143 |
| PR Review Agent | Recall | 1.0000 |
| PR Review Agent | F1 | 0.8333 |
| CI Debug Agent | 根因 Top-1 | 0.9333 |
| CI Debug Agent | 失败类型 Accuracy | 0.7333 |

### Issue 分类各类别

| 类别 | Precision | Recall | F1 | Support |
| --- | ---: | ---: | ---: | ---: |
| Bug | 0.5000 | 0.2000 | 0.2857 | 5 |
| Feature | 0.2667 | 0.8000 | 0.4000 | 5 |
| Documentation | 0.8000 | 1.0000 | 0.8889 | 4 |
| Test | 1.0000 | 1.0000 | 1.0000 | 4 |
| Ops | 0.7500 | 0.7500 | 0.7500 | 4 |
| Refactor | 0.0000 | 0.0000 | 0.0000 | 4 |
| Question | 0.0000 | 0.0000 | 0.0000 | 4 |

### CI 按失败类型

| 类型 | 样本数 | 类型准确率 | 根因 Top-1 |
| --- | ---: | ---: | ---: |
| build | 5 | 0.6000 | 0.8000 |
| dependency | 5 | 0.6000 | 0.8000 |
| environment | 5 | 0.8000 | 1.0000 |
| lint | 5 | 0.4000 | 1.0000 |
| permission | 5 | 1.0000 | 1.0000 |
| test | 5 | 1.0000 | 1.0000 |

### 解析鲁棒性对比（strict vs normalized）

| 模式 | Issue Accuracy | PR Recall | CI 根因 Top-1 | 兜底输出数 |
| --- | ---: | ---: | ---: | ---: |
| 严格 Pydantic 解析 | 0.5333 | 0.3333 | 0.9667 | 15 + 23 + 29 = 67 / 90 |
| 本地 schema 归一化 | 0.5333 | 1.0000 | 0.9333 | 0 / 90 |

严格解析下，67/90 条 LLM 输出因字段类型/缺失被整条丢弃并回退启发式；归一化后 0 条兜底。PR 召回从 33.3% 提升到 100%，说明瓶颈在解析而不是模型能力。CI 根因在 strict 下反而更高（96.7% vs 93.3%），是因为 strict 的 29/30 条结果全部来自关键词启发式，合成日志里关键词非常明显，不能当作 LLM 能力结论。

### Issue Agent 根因

30/30 条 Issue LLM 原始输出都不含 `category` 字段；提示词只要求 conclusion/priority/complexity 等字段，未要求 category。Agent 因此静默使用关键词启发式分类，导致 Refactor/Question 的 F1 为 0。修复提示词或把完整 JSON Schema 放进 prompt 后，Issue 分类应能恢复到与单 Agent 接近的水平。

## 实验③ RAG 消融

- 语料：70 个 chunk，查询：22 条
- Embedding：`BAAI/bge-m3`，Reranker：`bge-reranker-base`
- 说明：Vector branch uses BGE-M3 instead of project-default Qwen3-Embedding because no DashScope key/local Qwen embedding is available. Rerank uses BGE-reranker-base instead of qwen3-rerank API. Fusion, dedupe, parent limit and answer gate are the project's real code.

| 方案 | Recall@5 | MRR@5 | nDCG@5 |
| --- | ---: | ---: | ---: |
| A_vector | 0.9848 | 0.8598 | 0.8844 |
| B_union | 0.9848 | 0.8636 | 0.8873 |
| C_fusion | 0.9848 | 0.9242 | 0.9331 |
| D_full | 0.8939 | 0.8523 | 0.8558 |

- Answer Gate 通过率：1.0000
- 解读：加权融合 C 相对纯向量 A，MRR +0.0644（约 +7.5%）、nDCG +0.0487（约 +5.5%）；向量+BM25 简单并集 B 相对 A 几乎无提升（+0.004/+0.003）。D 使用本地 BGE reranker 后 Recall@5、MRR、nDCG 均下降，说明 rerank 不是无条件增益，cross-encoder 需要与语料/查询分布匹配；生产环境的 qwen3-rerank 需要单独验证。
- 注意：D 的 Answer Gate 关闭了 0.8 分数阈值（本地 reranker 分数与 Qwen 不可比），1.0 通过率只表示未触发证据冲突/指代澄清，不代表生产阈值下的通过率。

## 实验④ 上下文压缩保真

- 模型：`deepseek-chat`，总耗时：12.25 秒
- Token 用量：{'calls': 41, 'prompt_tokens': 83464, 'completion_tokens': 1572, 'total_tokens': 85036, 'errors': 0}

| 方案 | 上下文 Token | 相对节省 | 关键事实保留率 | 问答准确率 | 任务完成率 |
| --- | ---: | ---: | ---: | ---: | ---: |
| A_none | 7055 | 0.0000 | 1.0000 | 1.0000 | 1.0000 |
| B_truncate | 1054 | 0.8506 | 0.2000 | 0.2500 | 0.5000 |
| C_full | 1399 | 0.8017 | 0.5500 | 0.5000 | 0.7500 |

- A 与 C 回答一致率：0.5000
- 解读：C 比 B 保留更多事实（55% vs 20%）、问答准确率更高（50% vs 25%）、任务完成率更高（75% vs 50%），但两者都显著低于不压缩的 A（100%）。
- 根因：LLM 摘要与结构化记忆本次均成功生成（summary_mode=llm, memory_mode=llm），但摘要/记忆提示词没有覆盖全部关键实体；保真补充层只覆盖路径、命令、错误等约 10 类行，未覆盖 Redis TTL、表名、迁移文件、分支、PR 编号、负责人、截止时间等事实。

## 建议

1. **修复 IssueAgent 提示词**：把完整 `IssueAnalysisOutput` schema（尤其是 `category`、`summary`、`suggested_owner`、`owner_reason`）显式写进 prompt；修复后多 Agent 的质量缺口预计消失。
2. **把结构化输出容错下沉到生产代码**：严格 Pydantic 解析会丢弃 67/90 条有效 LLM 输出；建议采用本地字段归一化 + 仅对空/截断输出重试，避免整条结果回退启发式。
3. **rerank 需要分模型/分语料验证**：不要默认 rerank 一定提升；建议在真实标注集上对比 qwen3-rerank、无 rerank 和融合分数，必要时做分数校准或门控。
4. **压缩增加事实清单层**：在摘要/记忆 prompt 中显式要求保留文件路径、命令、决策、待办、错误、表/迁移名、分支/PR、负责人/截止时间等实体，并对这些实体做压缩后校验。
5. **多 Agent 只在独立子任务且延迟敏感时使用**：本实验中单 Agent 比并行多 Agent 快 5.5×、省 7.4× Token，且质量更高；多 Agent 的价值应体现在专业化、可观测性和交叉校验，而不是简单的三任务拆分。

## 口径与局限

- 实验②的测试集是为本次实验编写的合成标注集，不是生产人工标注数据；样例分布与真实 GitHub 仓库不同。
- 实验①使用相同的 10 个任务包，A 为一次单体 LLM 调用，B/C 共用 Planner、专用 Agent、Observer、Synthesis，仅 `max_parallel_tasks` 不同。
- 实验③使用本地 BGE-M3 和 BGE-reranker-base 替代项目默认的 Qwen3-Embedding 与 qwen3-rerank API；融合、去重、父块限额与 Answer Gate 使用项目真实代码。
- 实验④的 C 组使用项目真实的五层压缩函数（microcompact、预算化历史压缩、LLM 摘要、结构化记忆、保真补充），但未接入数据库与完整会话封存流程。
- 所有 LLM 用量取自 provider 返回的 usage；若 provider 未返回则使用项目 `estimate_tokens` 估算。
from __future__ import annotations

from typing import Any


def _issue(index: int, category: str, title: str, body: str) -> dict[str, Any]:
    return {
        "id": f"issue-{index:02d}",
        "expected_category": category,
        "issue": {
            "number": index,
            "title": title,
            "body": body,
            "labels": [],
            "state": "open",
            "author": "engineer",
            "assignees": [],
        },
    }


ISSUE_CASES: list[dict[str, Any]] = [
    _issue(1, "Bug", "登录接口在 token 过期后返回 500", "用户刷新页面时后端抛出 KeyError: 'sub'，前端只看到 500。预期应返回 401 并引导重新登录。"),
    _issue(2, "Bug", "导出 CSV 时中文全部变成问号", "Windows Excel 打开后乱码，文件按 utf-8 写入而不是 utf-8-sig，中文列名全部丢失。"),
    _issue(3, "Bug", "并发创建订单会重复扣减库存", "两个请求同时读取库存 1，都判断库存充足，最终库存变成 -1，产生超卖。"),
    _issue(4, "Bug", "移动端 Safari 点击下拉框没有反应", "iOS 17 上 select 组件被一个透明遮罩覆盖，点击事件无法触发。"),
    _issue(5, "Bug", "定时任务偶尔重复执行", "cron worker 在滚动部署时启动了两个实例，同一个清理任务被消费两次。"),
    _issue(6, "Feature", "支持按标签筛选 Issue 列表", "希望在 Issue 页面增加多选标签过滤，并保留当前排序方式。"),
    _issue(7, "Feature", "希望在 PR 页面显示 CI 重跑按钮", "审查者可以直接触发失败 workflow 的重跑，而不必跳转到 GitHub Actions。"),
    _issue(8, "Feature", "增加周报导出为 PDF", "团队希望把生成的工程周报下载为 PDF，包含图表和链接。"),
    _issue(9, "Feature", "支持 GitHub Enterprise 地址配置", "接入内网 GitHub Enterprise 时，需要自定义 API base URL 和证书。"),
    _issue(10, "Feature", "为团队成员增加技能标签", "分配 Issue 时希望根据语言、框架和历史模块匹配负责人。"),
    _issue(11, "Documentation", "README 的本地启动步骤缺少环境变量说明", "新同学不知道需要先复制 .env.example，也不知道哪些变量必填。"),
    _issue(12, "Documentation", "API 文档没有给出 429 限流错误示例", "客户端需要知道限流响应结构和重试建议。"),
    _issue(13, "Documentation", "部署指南里的 Docker 命令已过期", "文档里的镜像名和 compose 服务名已经与当前仓库不一致。"),
    _issue(14, "Documentation", "贡献指南没有说明提交信息格式", "希望补充 commit message 约定和 PR 模板填写示例。"),
    _issue(15, "Test", "为 retrieval 的父块扩展补充单测", "当前只测了检索排序，没有覆盖相邻块拼接和版本不一致的场景。"),
    _issue(16, "Test", "pytest 覆盖率门槛需要提高到 80%", "CI 目前不检查覆盖率，希望新增覆盖率报告并在低于阈值时失败。"),
    _issue(17, "Test", "增加 GitHub 分页同步的集成测试", "需要模拟 Link header 翻页、限流和部分失败，验证同步状态是否正确。"),
    _issue(18, "Test", "前端聊天组件缺少交互测试", "发送消息、流式渲染和错误提示都没有自动化测试。"),
    _issue(19, "Ops", "CI 的 Node 缓存导致 lockfile 不一致", "缓存恢复了旧 node_modules，npm ci 报错，构建随机失败。"),
    _issue(20, "Ops", "生产环境镜像构建时间超过 20 分钟", "希望增加多阶段构建和依赖层缓存，缩短发布等待时间。"),
    _issue(21, "Ops", "需要为 staging 增加自动回滚脚本", "部署失败时要能一键回滚到上一个镜像版本。"),
    _issue(22, "Ops", "GitHub Actions 权限不足，无法上传 artifact", "workflow 的 permissions 没有 actions: write，上传步骤被拒绝。"),
    _issue(23, "Refactor", "把仓库同步服务拆成 issue/pr/actions 三个模块", "当前 repos_sync.py 过长，职责混杂，希望按数据源拆分。"),
    _issue(24, "Refactor", "移除重复的 token 解析工具函数", "三个模块各自实现了一遍 JWT 解析，需要统一到一个工具函数。"),
    _issue(25, "Refactor", "将 chat.py 里的路由工厂抽成独立文件", "路由文件超过两千行，希望按工具域拆分，保持行为不变。"),
    _issue(26, "Refactor", "统一后端错误响应结构", "目前有的接口返回 detail，有的返回 error，客户端处理不一致。"),
    _issue(27, "Question", "RAG 的 score_threshold 为什么默认是 0.8？", "这个阈值适合哪些 embedding 和 reranker 组合，调整时需要注意什么？"),
    _issue(28, "Question", "这个项目如何在不启动 Milvus 的情况下演示？", "没有 Docker 环境时，哪些功能还能用，哪些会降级？"),
    _issue(29, "Question", "IssueAgent 和 PRReviewAgent 分别适合什么场景？", "两者都能做工程分析，团队应该如何选择调用？"),
    _issue(30, "Question", "为什么源码不进入向量库？", "源码检索为什么优先走 workspace 工具而不是 RAG？"),
]


def _pr(
    index: int,
    *,
    has_bug: bool,
    bug_type: str,
    bug_keywords: list[str],
    title: str,
    body: str,
    files: list[tuple[str, str, int, int]],
) -> dict[str, Any]:
    return {
        "id": f"pr-{index:02d}",
        "has_bug": has_bug,
        "bug_type": bug_type,
        "bug_keywords": bug_keywords,
        "pr": {
            "number": 200 + index,
            "title": title,
            "body": body,
            "state": "open",
            "author": "engineer",
            "base_branch": "main",
            "head_branch": f"feature/{index}",
            "comments": [],
            "files": [
                {
                    "filename": filename,
                    "status": "modified",
                    "additions": additions,
                    "deletions": deletions,
                    "patch": patch,
                }
                for filename, patch, additions, deletions in files
            ],
        },
    }


PR_CASES: list[dict[str, Any]] = [
    _pr(1, has_bug=True, bug_type="sql_injection", bug_keywords=["sql", "注入", "injection", "拼接"], title="Add user search endpoint", body="新增按用户名搜索用户的接口。", files=[("backend/app/repositories/user_repo.py", "+    query = f\"SELECT * FROM users WHERE name = '{name}'\"\n+    return db.execute(query)", 8, 0)]),
    _pr(2, has_bug=True, bug_type="missing_auth", bug_keywords=["授权", "权限", "auth", "authorization", "permission", "未校验"], title="Add admin export endpoint", body="管理员可以导出用户数据。", files=[("backend/app/api/routes/admin.py", "+@router.post(\"/admin/export\")\n+async def export_users(db: Session = Depends(get_db)):\n+    return build_export(db)", 12, 0)]),
    _pr(3, has_bug=True, bug_type="hardcoded_secret", bug_keywords=["secret", "密钥", "硬编码", "hardcoded"], title="Wire up payment provider", body="接入支付服务。", files=[("backend/app/core/config.py", "+STRIPE_SECRET_KEY = \"sk_live_51HxExampleRealLookingKey\"\n+PAYMENT_ENABLED = True", 6, 0)]),
    _pr(4, has_bug=True, bug_type="null_deref", bug_keywords=["空指针", "null", "none", "未判断", "属性"], title="Render profile page", body="个人主页展示用户资料。", files=[("backend/app/services/profile.py", "+    name = user.profile.name\n+    return {\"name\": name}", 5, 0)]),
    _pr(5, has_bug=True, bug_type="off_by_one", bug_keywords=["off-by-one", "越界", "边界", "最后"], title="Batch process items", body="批量处理待办事项。", files=[("backend/app/services/batch.py", "+    for i in range(len(items) - 1):\n+        process(items[i])", 6, 0)]),
    _pr(6, has_bug=True, bug_type="race_condition", bug_keywords=["race", "并发", "竞争", "锁"], title="Add inventory deduction", body="下单时扣减库存。", files=[("backend/app/services/order.py", "+    stock = db.query(Stock).first().count\n+    if stock >= qty:\n+        stock -= qty\n+        db.commit()", 10, 0)]),
    _pr(7, has_bug=True, bug_type="path_traversal", bug_keywords=["路径", "traversal", "穿越", "../"], title="Add attachment download", body="按文件名下载附件。", files=[("backend/app/api/routes/files.py", "+    path = os.path.join(UPLOAD_DIR, filename)\n+    return FileResponse(path)", 7, 0)]),
    _pr(8, has_bug=True, bug_type="n_plus_one", bug_keywords=["n+1", "循环查询", "性能"], title="Build report list", body="生成报告列表。", files=[("backend/app/services/report.py", "+    for row in rows:\n+        owner = db.query(User).filter(User.id == row.owner_id).first()\n+        output.append(owner.name)", 9, 0)]),
    _pr(9, has_bug=True, bug_type="missing_error_handling", bug_keywords=["错误处理", "异常", "未捕获", "error"], title="Fetch remote items", body="调用上游接口获取条目。", files=[("backend/app/services/github/client.py", "+    response = httpx.get(url)\n+    return response.json()[\"data\"][\"items\"]", 5, 0)]),
    _pr(10, has_bug=True, bug_type="broken_migration", bug_keywords=["迁移", "migration", "not null", "默认值"], title="Add email column", body="为用户表增加邮箱字段。", files=[("backend/migrations/0007_add_email.sql", "+ALTER TABLE users ADD COLUMN email VARCHAR(255) NOT NULL;", 3, 0)]),
    _pr(11, has_bug=True, bug_type="xss", bug_keywords=["xss", "跨站", "dangerouslysetinnerhtml"], title="Render rich comment", body="评论支持富文本。", files=[("frontend/components/comment.tsx", "+  return <div dangerouslySetInnerHTML={{ __html: comment.body }} />;", 4, 0)]),
    _pr(12, has_bug=True, bug_type="deserialization", bug_keywords=["反序列化", "pickle", "deserialization"], title="Import serialized state", body="支持导入导出的状态文件。", files=[("backend/app/api/routes/imports.py", "+    state = pickle.loads(request.body)\n+    restore(state)", 6, 0)]),
    _pr(13, has_bug=True, bug_type="missing_timeout", bug_keywords=["超时", "timeout"], title="Add webhook dispatch", body="向外部服务发送 webhook。", files=[("backend/app/services/webhook.py", "+    response = httpx.post(target_url, json=payload)\n+    return response.status_code", 5, 0)]),
    _pr(14, has_bug=True, bug_type="input_validation", bug_keywords=["类型", "int", "校验", "溢出", "validate"], title="Set item quantity", body="更新购物车数量。", files=[("backend/app/services/price.py", "+    quantity = int(request.args[\"quantity\"])\n+    total = unit_price * quantity", 5, 0)]),
    _pr(15, has_bug=True, bug_type="memory_leak", bug_keywords=["内存", "泄漏", "leak", "缓存"], title="Cache search results", body="提升搜索性能。", files=[("backend/app/services/cache.py", "+_CACHE = {}\n+def get(key):\n+    if key not in _CACHE:\n+        _CACHE[key] = expensive_query(key)\n+    return _CACHE[key]", 8, 0)]),
    _pr(16, has_bug=False, bug_type="clean", bug_keywords=[], title="Add tests for token refresh", body="补充刷新 token 的单元测试。", files=[("backend/app/tests/test_auth.py", "+def test_refresh_token_expiry():\n+    assert refresh(\"expired\") is None", 12, 0)]),
    _pr(17, has_bug=False, bug_type="clean", bug_keywords=[], title="Document API pagination", body="补充分页参数说明。", files=[("docs/api/openapi.md", "+### Pagination\n+Use `limit` and `offset` query parameters.", 6, 0)]),
    _pr(18, has_bug=False, bug_type="clean", bug_keywords=[], title="Rename helper for clarity", body="重命名局部变量，不改变行为。", files=[("backend/app/services/repos_sync.py", "-    payload = build()\n+    sync_payload = build()\n-    return store(payload)\n+    return store(sync_payload)", 3, 3)]),
    _pr(19, has_bug=False, bug_type="clean", bug_keywords=[], title="Add structured logging", body="在同步失败时记录上下文。", files=[("backend/app/services/repos_sync.py", "+logger.info(\"sync started repo=%s\", repo.full_name)\n+logger.info(\"sync finished repo=%s\", repo.full_name)", 4, 0)]),
    _pr(20, has_bug=False, bug_type="clean", bug_keywords=[], title="Add type hints to chunker", body="为切分函数补充类型注解。", files=[("backend/app/services/rag/chunking.py", "-def chunk_document(text, source_path=\"document.txt\"):\n+def chunk_document(text: str, source_path: str = \"document.txt\"):", 2, 1)]),
    _pr(21, has_bug=False, bug_type="clean", bug_keywords=[], title="Split large sync function", body="把分页循环抽成独立函数。", files=[("backend/app/services/repos_sync.py", "+def _sync_pages(client, url):\n+    return list(client.paginate(url))", 10, 4)]),
    _pr(22, has_bug=False, bug_type="clean", bug_keywords=[], title="Add index to documents repo_id", body="加快按仓库过滤的查询。", files=[("backend/migrations/0008_documents_index.sql", "+CREATE INDEX IF NOT EXISTS ix_documents_repo_id ON documents(repo_id);", 2, 0)]),
    _pr(23, has_bug=False, bug_type="clean", bug_keywords=[], title="Improve empty-state copy", body="优化 UI 文案。", files=[("frontend/components/rag/empty-state.tsx", "+  <p>还没有上传资料，先添加一份文档吧。</p>", 2, 1)]),
    _pr(24, has_bug=False, bug_type="clean", bug_keywords=[], title="Set safer default timeout", body="为新建 HTTP 客户端设置默认超时。", files=[("backend/app/services/github/client.py", "+DEFAULT_TIMEOUT = 30\n+client = httpx.Client(timeout=DEFAULT_TIMEOUT)", 2, 0)]),
    _pr(25, has_bug=False, bug_type="clean", bug_keywords=[], title="Add module docstring", body="补充模块说明。", files=[("backend/app/services/context_compression.py", "+\"\"\"Context compression helpers.\"\"\"\n", 1, 0)]),
    _pr(26, has_bug=False, bug_type="clean", bug_keywords=[], title="Add OpenAPI response description", body="补充 200 响应说明。", files=[("backend/app/api/routes/rag.py", "+@router.get(\"/status\", summary=\"RAG 状态\")\n async def get_rag_status():", 1, 0)]),
    _pr(27, has_bug=False, bug_type="clean", bug_keywords=[], title="Format imports", body="按 isort 规则排序导入。", files=[("backend/app/services/rag/retrieval.py", "-import re, math\n+import math\n+import re", 2, 1)]),
    _pr(28, has_bug=False, bug_type="clean", bug_keywords=[], title="Add CI cache key", body="按 lockfile 哈希缓存依赖。", files=[(".github/workflows/ci.yml", "+      - uses: actions/cache@v4\n+        with:\n+          key: node-${{ hashFiles('package-lock.json') }}", 5, 0)]),
    _pr(29, has_bug=False, bug_type="clean", bug_keywords=[], title="Extract constant", body="把重复字符串提取为常量。", files=[("backend/app/services/llm/prompts.py", "+MAX_CONTEXT_CHARS = 24000\n", 1, 0)]),
    _pr(30, has_bug=False, bug_type="clean", bug_keywords=[], title="Add test fixture factory", body="新增测试数据工厂。", files=[("backend/app/tests/factories.py", "+def make_issue(**overrides):\n+    return {\"title\": \"demo\", \"body\": \"\", **overrides}", 4, 0)]),
]


def _ci(
    index: int,
    failure_type: str,
    keywords: list[str],
    name: str,
    logs: str,
    jobs: list[str],
) -> dict[str, Any]:
    return {
        "id": f"ci-{index:02d}",
        "expected_failure_type": failure_type,
        "expected_root_keywords": keywords,
        "workflow_run": {
            "github_run_id": 300 + index,
            "name": name,
            "status": "completed",
            "conclusion": "failure",
            "html_url": f"https://github.com/demo/repo/actions/runs/{300 + index}",
            "logs_text": logs,
            "jobs": [
                {
                    "name": job,
                    "conclusion": "failure",
                    "steps": [{"name": "Run checks", "conclusion": "failure"}],
                }
                for job in jobs
            ],
        },
    }


CI_CASES: list[dict[str, Any]] = [
    _ci(1, "test", ["test_refresh_token_expiry", "assertionerror", "401", "断言"], "pytest-auth", "tests/test_auth.py::test_refresh_token_expiry\nAssertionError: assert 500 == 401\nE   assert 500 == 401", ["pytest"]),
    _ci(2, "test", ["test_export_encoding", "utf-8-sig", "断言"], "pytest-export", "tests/test_export.py::test_export_encoding\nAssertionError: b'\\xe4\\xb8\\xad' not found in exported csv", ["pytest"]),
    _ci(3, "test", ["test_inventory_concurrency", "assert -1", "断言"], "pytest-order", "tests/test_order.py::test_inventory_concurrency\nAssertionError: assert -1 >= 0", ["pytest"]),
    _ci(4, "test", ["test_retrieval_parent_expansion", "parent_id", "断言"], "pytest-rag", "tests/test_rag.py::test_retrieval_parent_expansion\nAssertionError: assert [] == [chunk-2]", ["pytest"]),
    _ci(5, "test", ["test_chunk_size_limit", "max_chars", "断言"], "pytest-chunking", "tests/test_chunking.py::test_chunk_size_limit\nAssertionError: chunk content exceeded max_chars", ["pytest"]),
    _ci(6, "build", ["ts2345", "type error", "类型"], "web-build", "next build\n./app/chat/page.tsx:42:18\nType error: Argument of type 'string' is not assignable to parameter of type 'number'.\nTS2345", ["build"]),
    _ci(7, "build", ["ts2307", "cannot find module", "模块"], "web-build", "next build\nType error: Cannot find module '@/lib/rag' or its corresponding type declarations.\nTS2307", ["build"]),
    _ci(8, "build", ["webpack", "module parse failed", "构建"], "web-build", "webpack 5.90.0\nModule parse failed: Unexpected token (12:7)\nYou may need an appropriate loader.", ["build"]),
    _ci(9, "build", ["rustc", "e0308", "mismatched types"], "native-build", "error[E0308]: mismatched types\n --> src/main.rs:18:9\nexpected `String`, found `&str`", ["build"]),
    _ci(10, "build", ["java", "compilation failure", "cannot find symbol"], "java-build", "[ERROR] COMPILATION ERROR\n[ERROR] /src/Order.java:[22,9] cannot find symbol", ["build"]),
    _ci(11, "dependency", ["eresolve", "dependency", "依赖", "lockfile"], "npm-ci", "npm ERR! code ERESOLVE\nnpm ERR! ERESOLVE unable to resolve dependency tree\nnpm ERR! peer react@\"^18\" from react-dom@18.2.0", ["install"]),
    _ci(12, "dependency", ["no matching distribution", "pip", "依赖"], "pip-install", "ERROR: Could not find a version that satisfies the requirement pymilvus==9.9.9\nERROR: No matching distribution found for pymilvus==9.9.9", ["install"]),
    _ci(13, "dependency", ["module not found", "cannot find module", "模块"], "node-install", "Error: Cannot find module 'langchain-openai'\nRequire stack:\n- /app/agent.js", ["install"]),
    _ci(14, "dependency", ["lockfile", "out of sync", "package-lock"], "npm-ci", "npm ci can only install packages when your package.json and package-lock.json are in sync.\nMissing: zod@3.24.0 from lock file", ["install"]),
    _ci(15, "dependency", ["hash mismatch", "integrity", "checksum"], "python-poetry", "Installing dependencies from lock file\n  Hash mismatch for package 'fastapi': expected sha256:abc, got sha256:def", ["install"]),
    _ci(16, "permission", ["resource not accessible", "permission", "权限", "403"], "gh-artifact", "Error: Resource not accessible by integration\nHttpError: 403 Forbidden\nResource not accessible by integration", ["upload-artifact"]),
    _ci(17, "permission", ["permission denied", "eacces", "权限"], "linux-test", "PermissionError: [Errno 13] Permission denied: '/workspace/.cache/pip'", ["test"]),
    _ci(18, "permission", ["forbidden", "403", "token"], "api-smoke", "httpx.HTTPStatusError: Client error '403 Forbidden' for url 'https://api.github.com/repos/demo/private'\nThe token lacks repository scope.", ["smoke"]),
    _ci(19, "permission", ["access denied", "denied", "权限"], "docker-push", "denied: requested access to the resource is denied\nunauthorized: authentication required", ["publish"]),
    _ci(20, "permission", ["permission", "权限", "protected branch"], "merge-check", "remote: error: GH006: Protected branch update failed\nThe required status check is missing permission.", ["merge"]),
    _ci(21, "environment", ["database_url", "environment variable", "环境变量"], "pytest-api", "RuntimeError: DATABASE_URL environment variable is not set\npytest exited with code 1", ["test"]),
    _ci(22, "environment", ["openai_api_key", "environment variable", "环境变量"], "agent-test", "KeyError: 'OPENAI_API_KEY'\nMissing env var in workflow env block.", ["test"]),
    _ci(23, "environment", ["missing env", "secret", "not set"], "deploy", "Error: required secret DOCKER_PASSWORD is not set in repository secrets.", ["deploy"]),
    _ci(24, "environment", ["redis_url", "connection refused", "环境变量"], "integration-test", "redis.exceptions.ConnectionError: Error 111 connecting to redis:6379\nREDIS_URL was rendered empty.", ["test"]),
    _ci(25, "environment", ["node_env", "environment variable", "环境变量"], "web-test", "ReferenceError: process.env.NODE_ENV is undefined\nNODE_ENV environment variable was not provided.", ["test"]),
    _ci(26, "lint", ["eslint", "no-unused-vars", "lint"], "web-lint", "/app/components/chat.tsx\n  12:7  error  'unused' is assigned a value but never used  no-unused-vars", ["lint"]),
    _ci(27, "lint", ["ruff", "f401", "lint"], "python-lint", "backend/app/api/routes/rag.py:3:1: F401 'typing.Any' imported but unused\nFound 1 error.", ["lint"]),
    _ci(28, "lint", ["prettier", "format", "格式"], "web-format", "[warn] components/chat.tsx\n[warn] Code style issues found in the above file. Run Prettier to fix.", ["format"]),
    _ci(29, "lint", ["mypy", "type", "union-attr"], "python-typecheck", "backend/app/services/rag/qa.py:42: error: Item \"None\" of \"Document | None\" has no attribute \"content\"  [union-attr]", ["typecheck"]),
    _ci(30, "lint", ["golangci-lint", "ineffassign", "lint"], "go-lint", "internal/server/handler.go:88:2: ineffectual assignment to err (ineffassign)", ["lint"]),
]


GLOBAL_BUG_KEYWORDS = [
    "sql", "注入", "injection", "拼接", "授权", "权限", "auth", "authorization",
    "permission", "未校验", "secret", "密钥", "硬编码", "hardcoded", "空指针", "null",
    "none", "未判断", "off-by-one", "越界", "边界", "最后", "race", "并发", "竞争",
    "锁", "路径穿越", "traversal", "../", "n+1", "循环查询", "错误处理", "未捕获",
    "迁移", "migration", "not null", "默认值", "xss", "跨站", "dangerouslysetinnerhtml",
    "反序列化", "pickle", "超时", "timeout", "int", "溢出", "内存", "泄漏", "leak",
    "缓存", "类型", "校验",
]

PR_GENERIC_PHRASES = [
    "边界条件和异常路径",
    "缺少测试覆盖证明",
    "敏感文件变更需要重点验证",
    "失败 ci 阻塞合并",
    "review 评论尚需确认",
]

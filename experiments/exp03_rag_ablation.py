from __future__ import annotations

import gc
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from common import mean, mrr_at_k, ndcg_at_k, recall_at_k, write_json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Document
from app.services.rag.answer_gate import evaluate_answer_gate
from app.services.rag.chunking import chunk_document
from app.services.rag.rerank import rerank_documents
from app.services.rag.retrieval import (
    _deduplicate_candidates,
    _keyword_candidates,
    _limit_parent_occupancy,
    _merge_candidates,
)

ROOT = Path(__file__).resolve().parents[1]
REPO_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
TOP_K = 5
FETCH_LIMIT = 50

CORPUS_GLOBS = [
    "README.md",
    "docs/**/*.md",
    "backend/app/skills/**/*.md",
]

QUERIES: list[dict[str, Any]] = [
    {"id": "q01", "query": "后端默认监听哪个端口？", "keyword": "localhost:8000", "doc": "README.md"},
    {"id": "q02", "query": "前端本地开发默认地址是什么？", "keyword": "localhost:3000", "doc": "README.md"},
    {"id": "q03", "query": "RAG 默认使用哪个 embedding 模型？", "keyword": "Qwen3-Embedding-0.6B", "doc": "README.md"},
    {"id": "q04", "query": "默认的 rerank 模型是什么？", "keyword": "qwen3-rerank", "doc": "README.md"},
    {"id": "q05", "query": "知识库支持哪些文件格式？", "keyword": "TXT、Markdown、PDF、DOCX、JSON、CSV", "doc": "README.md"},
    {"id": "q06", "query": "重建 RAG 索引调用哪个接口？", "keyword": "reindex", "doc": "README.md"},
    {"id": "q07", "query": "RAGAS 评测包含哪五项核心指标？", "keyword": "Context Precision", "doc": "README.md"},
    {"id": "q08", "query": "Agent 在对话中搜索知识库使用哪个工具？", "keyword": "rag.search_similar_documents", "doc": "README.md"},
    {"id": "q09", "query": "源码检索优先使用哪个工具？", "keyword": "workspace.search_code", "doc": "README.md"},
    {"id": "q10", "query": "RAG 问答接口的路径是什么？", "keyword": "/api/rag/{repo_id}/ask", "doc": "README.md"},
    {"id": "q11", "query": "正式员工每年有多少天带薪年假？", "keyword": "10 天带薪年假", "doc": "docs/examples/rag_employee_handbook.md"},
    {"id": "q12", "query": "年假需要提前多久申请？", "keyword": "提前 3 个工作日", "doc": "docs/examples/rag_employee_handbook.md"},
    {"id": "q13", "query": "连续休假超过几天需要部门负责人二次审批？", "keyword": "超过 5 天", "doc": "docs/examples/rag_employee_handbook.md"},
    {"id": "q14", "query": "未使用的年假最晚什么时候用完？", "keyword": "次日 3 月 31 日", "doc": "docs/examples/rag_employee_handbook.md", "fallback_keyword": "3 月 31 日"},
    {"id": "q15", "query": "员工每周最多可以申请几天远程办公？", "keyword": "每周最多申请 2 天", "doc": "docs/examples/rag_employee_handbook.md"},
    {"id": "q16", "query": "远程办公申请需要在什么时候前提交？", "keyword": "18:00 前", "doc": "docs/examples/rag_employee_handbook.md"},
    {"id": "q17", "query": "P0 事故要求值班工程师多久响应？", "keyword": "5 分钟内响应", "doc": "docs/examples/rag_employee_handbook.md"},
    {"id": "q18", "query": "事故处理期间多久同步一次进展？", "keyword": "每 30 分钟", "doc": "docs/examples/rag_employee_handbook.md"},
    {"id": "q19", "query": "服务恢复后多久必须完成复盘文档？", "keyword": "2 个工作日内", "doc": "docs/examples/rag_employee_handbook.md"},
    {"id": "q20", "query": "5000 元以上的费用需要谁审批？", "keyword": "部门负责人审批", "doc": "docs/examples/rag_employee_handbook.md"},
    {"id": "q21", "query": "一线城市差旅住宿标准是多少？", "keyword": "600 元", "doc": "docs/examples/rag_employee_handbook.md"},
    {"id": "q22", "query": "发票和付款凭证需要在多久内上传？", "keyword": "30 天内", "doc": "docs/examples/rag_employee_handbook.md"},
]


def build_corpus() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_files: set[str] = set()
    for pattern in CORPUS_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            if not path.is_file() or path.suffix.lower() != ".md":
                continue
            relative = str(path.relative_to(ROOT))
            if relative in seen_files:
                continue
            seen_files.add(relative)
            text = path.read_text(encoding="utf-8")
            chunks = chunk_document(text, relative, max_chars=400, overlap=50)
            for chunk in chunks:
                records.append(
                    {
                        "chunk_id": chunk["chunk_id"],
                        "parent_id": chunk["parent_id"],
                        "child_index": chunk["child_index"],
                        "doc": relative,
                        "title": f"{relative} · {chunk.get('section_title') or '正文'}",
                        "content": chunk["content"],
                        "section_title": chunk.get("section_title"),
                    }
                )
    return records


def relevant_ids(corpus: list[dict[str, Any]], query: dict[str, Any]) -> list[str]:
    keywords = [query["keyword"]]
    if query.get("fallback_keyword"):
        keywords.append(query["fallback_keyword"])
    matches = [
        item["chunk_id"]
        for item in corpus
        if item["doc"] == query["doc"] and any(keyword in item["content"] for keyword in keywords)
    ]
    if not matches:
        matches = [
            item["chunk_id"]
            for item in corpus
            if any(keyword in item["content"] for keyword in keywords)
        ]
    return sorted(set(matches))


def build_sqlite(corpus: list[dict[str, Any]]) -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    for index, item in enumerate(corpus):
        session.add(
            Document(
                id=uuid.uuid5(uuid.NAMESPACE_URL, f"chunk:{index}"),
                repo_id=REPO_ID,
                source_type="project_doc",
                source_id=uuid.uuid5(uuid.NAMESPACE_URL, item["parent_id"]),
                title=item["title"][:500],
                content=item["content"],
                meta={
                    "path": item["doc"],
                    "chunk_id": item["chunk_id"],
                    "parent_id": item["parent_id"],
                    "child_index": item["child_index"],
                    "section_title": item["section_title"],
                },
            )
        )
    session.commit()
    return session


def _candidate(record: dict[str, Any], *, vector: float = 0.0, keyword: float = 0.0) -> dict[str, Any]:
    return {
        "id": record["chunk_id"],
        "title": record["title"],
        "source_type": "project_doc",
        "source_id": str(uuid.uuid5(uuid.NAMESPACE_URL, record["parent_id"])),
        "score": max(vector, keyword),
        "vector_score": vector,
        "keyword_score": keyword,
        "metadata": {
            "path": record["doc"],
            "chunk_id": record["chunk_id"],
            "parent_id": record["parent_id"],
            "child_index": record["child_index"],
            "section_title": record["section_title"],
        },
        "snippet": record["content"][:260],
        "_raw_content": record["content"],
        "retrieval": {"sources": ["vector"] if vector else ["keyword"]},
    }


def _rank_interleave(vector_items: list[dict[str, Any]], keyword_items: list[dict[str, Any]], limit: int = FETCH_LIMIT) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for index in range(max(len(vector_items), len(keyword_items))):
        for items in (vector_items, keyword_items):
            if index >= len(items):
                continue
            item = items[index]
            key = str((item.get("metadata") or {}).get("chunk_id") or item.get("id"))
            if key in seen:
                continue
            seen.add(key)
            output.append(item)
            if len(output) >= limit:
                return output
    return output


def _load_embedder(model_name: str):
    import torch
    import transformers.modeling_utils as modeling_utils
    from transformers import AutoModel, AutoTokenizer

    modeling_utils.check_torch_load_is_safe = lambda: None
    tokenizer = AutoTokenizer.from_pretrained(model_name, local_files_only=True)
    model = AutoModel.from_pretrained(model_name, local_files_only=True)
    model.eval()

    def encode(texts: list[str], batch_size: int = 16) -> np.ndarray:
        batches = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            inputs = tokenizer(batch, padding=True, truncation=True, max_length=512, return_tensors="pt")
            with torch.no_grad():
                output = model(**inputs)
            vectors = torch.nn.functional.normalize(output.last_hidden_state[:, 0], p=2, dim=1)
            batches.append(vectors.cpu().numpy())
        return np.concatenate(batches, axis=0)

    return encode


def _prepare_reranker():
    try:
        import torch
        import transformers.modeling_utils as modeling_utils
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        modeling_utils.check_torch_load_is_safe = lambda: None
        model_name = "BAAI/bge-reranker-base"
        tokenizer = AutoTokenizer.from_pretrained(model_name, local_files_only=True)
        model = AutoModelForSequenceClassification.from_pretrained(
            model_name, local_files_only=True
        )
        model.eval()

        def score(query: str, documents: list[str]) -> list[float]:
            inputs = tokenizer(
                [query] * len(documents),
                documents,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            )
            with torch.no_grad():
                logits = model(**inputs).logits
            return [float(item) for item in logits.reshape(-1).tolist()]

        return score, "bge-reranker-base"
    except Exception as exc:  # noqa: BLE001
        print(f"reranker unavailable, fallback to heuristic: {exc}")
        return None, "heuristic"


def main() -> None:
    started = time.perf_counter()
    corpus = build_corpus()
    print(f"corpus chunks: {len(corpus)}")
    query_relevant = {query["id"]: relevant_ids(corpus, query) for query in QUERIES}
    missing = {qid: ids for qid, ids in query_relevant.items() if not ids}
    if missing:
        print(f"WARNING: queries without relevant chunks: {missing}")

    model_name = "BAAI/bge-m3"
    print(f"loading embedding model: {model_name}")
    embedder = _load_embedder(model_name)
    chunk_texts = [item["content"] for item in corpus]
    chunk_embeddings = embedder(chunk_texts, batch_size=16)
    query_embeddings = embedder([query["query"] for query in QUERIES], batch_size=8)
    del embedder
    gc.collect()

    session = build_sqlite(corpus)
    reranker, reranker_name = _prepare_reranker()
    print(f"reranker: {reranker_name}")

    per_query: dict[str, dict[str, Any]] = {}
    for query_index, query in enumerate(QUERIES):
        vector_scores = np.asarray(chunk_embeddings @ query_embeddings[query_index]).reshape(-1)
        order = np.argsort(-vector_scores)
        vector_items: list[dict[str, Any]] = []
        max_score = max(float(vector_scores[index]) for index in order[:FETCH_LIMIT]) or 1.0
        for rank_index in order[:FETCH_LIMIT]:
            record = corpus[int(rank_index)]
            normalized = max(0.0, float(vector_scores[int(rank_index)])) / max_score
            item = _candidate(record, vector=round(normalized, 4))
            item["vector_score_raw"] = round(float(vector_scores[int(rank_index)]), 6)
            item["vector_rank"] = len(vector_items) + 1
            item["retrieval"] = {
                "sources": ["vector"],
                "vector_score": item["vector_score"],
                "vector_score_raw": item["vector_score_raw"],
                "vector_rank": item["vector_rank"],
                "vector_backend": "bge-m3",
            }
            vector_items.append(item)

        keyword_rows = _keyword_candidates(
            session,
            REPO_ID,
            query["query"],
            ["project_doc"],
            FETCH_LIMIT,
            None,
        )
        keyword_by_chunk: dict[str, dict[str, Any]] = {}
        for row in keyword_rows:
            chunk_id = str((row.get("metadata") or {}).get("chunk_id") or row.get("id"))
            keyword_by_chunk[chunk_id] = row
        keyword_items = list(keyword_by_chunk.values())[:FETCH_LIMIT]

        group_a = [item["id"] for item in vector_items[:TOP_K]]
        union = _rank_interleave(vector_items, keyword_items, FETCH_LIMIT)
        group_b = [str((item.get("metadata") or {}).get("chunk_id") or item.get("id")) for item in union[:TOP_K]]
        merged = _merge_candidates(vector_items, keyword_items)
        group_c_items = merged[:TOP_K]
        group_c = [str((item.get("metadata") or {}).get("chunk_id") or item.get("id")) for item in group_c_items]

        deduped, duplicates_removed = _deduplicate_candidates(merged)
        aggregated, parent_removed = _limit_parent_occupancy(deduped)
        rerank_pool = aggregated[:24]
        if reranker is not None:
            documents = [
                f"{item.get('title') or ''}\n{item.get('_raw_content') or item.get('snippet') or ''}"[:4000]
                for item in rerank_pool
            ]
            scores = reranker(query["query"], documents)
            reranked = []
            for item, score in zip(rerank_pool, scores):
                value = float(score)
                reranked.append(
                    {
                        **item,
                        "score": round(value, 6),
                        "rerank_score": round(value, 6),
                        "retrieval": {**(item.get("retrieval") or {}), "rerank_mode": reranker_name, "rerank_score": round(value, 6)},
                    }
                )
            reranked.sort(key=lambda item: float(item.get("rerank_score") or 0.0), reverse=True)
        else:
            reranked = rerank_documents(query["query"], rerank_pool, TOP_K)
        group_d_items = reranked[:TOP_K]
        group_d = [str((item.get("metadata") or {}).get("chunk_id") or item.get("id")) for item in group_d_items]
        gate = evaluate_answer_gate(query["query"], group_d_items, score_threshold=0.0, threshold_enabled=False)

        per_query[query["id"]] = {
            "query": query["query"],
            "relevant": query_relevant[query["id"]],
            "groups": {"A_vector": group_a, "B_union": group_b, "C_fusion": group_c, "D_full": group_d},
            "gate": gate,
            "duplicates_removed": duplicates_removed,
            "parent_overflow_removed": parent_removed,
        }

    metrics: dict[str, dict[str, float]] = {}
    for group in ("A_vector", "B_union", "C_fusion", "D_full"):
        recalls, mrrs, ndcgs = [], [], []
        for query in QUERIES:
            relevant = set(query_relevant[query["id"]])
            ranked = per_query[query["id"]]["groups"][group]
            recalls.append(recall_at_k(relevant, ranked, TOP_K))
            mrrs.append(mrr_at_k(relevant, ranked, TOP_K))
            ndcgs.append(ndcg_at_k(relevant, ranked, TOP_K))
        metrics[group] = {
            "recall_at_5": mean(recalls),
            "mrr_at_5": mean(mrrs),
            "ndcg_at_5": mean(ndcgs),
        }

    gate_pass = sum(1 for item in per_query.values() if item["gate"]["decision"] == "answer") / max(len(QUERIES), 1)
    payload = {
        "experiment": "exp03_rag_ablation",
        "corpus_files": sorted({item["doc"] for item in corpus}),
        "chunk_count": len(corpus),
        "query_count": len(QUERIES),
        "embedding_model": model_name,
        "reranker": reranker_name,
        "notes": "Vector branch uses BGE-M3 instead of project-default Qwen3-Embedding because no DashScope key/local Qwen embedding is available. Rerank uses BGE-reranker-base instead of qwen3-rerank API. Fusion, dedupe, parent limit and answer gate are the project's real code.",
        "metrics": metrics,
        "gate_pass_rate": round(gate_pass, 4),
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "per_query": per_query,
    }
    path = write_json("exp03_results.json", payload)
    print(json.dumps({"chunk_count": len(corpus), "query_count": len(QUERIES), "metrics": metrics, "gate_pass_rate": round(gate_pass, 4), "reranker": reranker_name}, ensure_ascii=False, indent=2))
    print(f"saved: {path}")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""轻量级本地检索与可选云端诊断服务。"""

import copy
import json
import os
import re
from pathlib import Path

import requests


class KeywordBackend:
    """Deterministic retrieval backend used by default and as a fallback."""

    name = "keyword"

    def __init__(self, tokenize):
        self._tokenize = tokenize

    def search(self, docs, query, top_k):
        query_tokens = self._tokenize(query)
        query_set = set(query_tokens)
        scores = []
        for doc in docs:
            doc_tokens = self._tokenize(doc["text"])
            doc_set = set(doc_tokens)
            intersection = query_set.intersection(doc_set)
            if not query_tokens or not doc_tokens:
                score = 0.0
            else:
                coverage = len(intersection) / max(1, len(query_set))
                precision = len(intersection) / max(1, len(doc_set))
                score = 0.72 * coverage + 0.28 * precision
                for phrase in re.findall(r"[A-Za-z0-9-]{3,}|[\u4e00-\u9fff]{2,6}", query):
                    if phrase.lower() in doc["text"].lower():
                        score += 0.025
                score = min(score, 1.0)
            scores.append((score, doc))
        scores.sort(key=lambda item: item[0], reverse=True)
        result = []
        for score, doc in scores[:top_k]:
            item = copy.deepcopy(doc)
            item.update({
                "score": round(score, 4),
                "matched_terms": list(set(self._tokenize(item["text"])).intersection(query_set))[:8],
                "backend": self.name,
            })
            result.append(item)
        return result


class ChromaBackend:
    """Optional Chroma adapter. Importing this module never requires Chroma."""

    name = "chroma"

    def __init__(self, path, embedding_model=""):
        import chromadb

        self.client = chromadb.PersistentClient(path=str(path))
        kwargs = {}
        if embedding_model:
            from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
            kwargs["embedding_function"] = SentenceTransformerEmbeddingFunction(model_name=embedding_model)
        self.collection = self.client.get_or_create_collection("demo_knowledge", **kwargs)

    def ensure_documents(self, docs):
        existing = self.collection.count()
        if existing >= len(docs):
            return
        self.collection.upsert(
            ids=[f"demo-{index}" for index in range(len(docs))],
            documents=[doc["text"] for doc in docs],
            metadatas=[{"source": doc.get("source", "合成演示知识库")} for doc in docs],
        )

    def search(self, docs, query, top_k):
        self.ensure_documents(docs)
        response = self.collection.query(query_texts=[query or "通用设备点检"], n_results=top_k)
        result = []
        distances = (response.get("distances") or [[0.0]])[0]
        documents = response.get("documents") or [[]]
        for index, text in enumerate(documents[0]):
            distance = distances[index] if index < len(distances) else 0.0
            metadata_rows = (response.get("metadatas") or [[]])[0]
            metadata = metadata_rows[index] if index < len(metadata_rows) else {}
            result.append({
                "text": text,
                "source": metadata.get("source", "合成演示知识库"),
                "score": round(max(0.0, 1.0 - float(distance)), 4),
                "matched_terms": [],
                "backend": self.name,
            })
        return result


class VectorService:
    """使用公开的合成知识库完成可解释检索，云端模型作为可选增强。"""

    def __init__(self):
        knowledge_path = Path(__file__).resolve().parent / "data" / "demo_knowledge_base.json"
        with knowledge_path.open("r", encoding="utf-8") as handle:
            self.knowledge_base = json.load(handle)
        self.backend_name = "keyword"
        self.backend_error = ""
        self.backend = KeywordBackend(self._tokenize)
        self.last_llm_status = self._offline_llm_status("未配置云端密钥")
        if os.getenv("VECTOR_BACKEND", "keyword").lower() == "chroma":
            try:
                db_path = Path(os.getenv("VECTOR_DB_PATH", str(knowledge_path.parent / "chroma")))
                self.backend = ChromaBackend(db_path, os.getenv("EMBEDDING_MODEL", "").strip())
                self.backend_name = "chroma"
            except Exception as exc:
                self.backend_error = f"{type(exc).__name__}: {exc}"

    @staticmethod
    def _offline_llm_status(reason):
        return {
            "provider": os.getenv("LLM_PROVIDER", "qwen").strip() or "qwen",
            "model": os.getenv("LLM_MODEL", "qwen-plus").strip() or "qwen-plus",
            "configured": bool(os.getenv("LLM_API_KEY", "").strip()),
            "active": "offline",
            "error": reason,
        }

    def llm_capabilities(self):
        """Return a non-sensitive snapshot suitable for the public capabilities API."""
        status = dict(self.last_llm_status)
        status["configured"] = bool(os.getenv("LLM_API_KEY", "").strip())
        status["provider"] = os.getenv("LLM_PROVIDER", "qwen").strip() or "qwen"
        status["model"] = os.getenv("LLM_MODEL", "qwen-plus").strip() or "qwen-plus"
        return status

    def _tokenize(self, text):
        """中文使用单字和二元词，英文使用单词，避免整句中文成为单一 token。"""
        text = (text or "").lower()
        tokens = re.findall(r"[a-z0-9_.+-]+", text)
        for run in re.findall(r"[\u4e00-\u9fff]+", text):
            tokens.extend(list(run))
            tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
        return tokens

    def search_similar(self, query, top_k=2, dynamic_cases=None):
        """结合静态演示知识和审核案例执行混合关键词匹配。"""
        static_docs = self.backend.search(self.knowledge_base, query, top_k)
        if dynamic_cases:
            dynamic_docs = KeywordBackend(self._tokenize).search(dynamic_cases, query, top_k)
            static_docs.extend(dynamic_docs)
            static_docs.sort(key=lambda item: item.get("score", 0), reverse=True)
        formatted_docs = static_docs[:top_k]
        return formatted_docs

    def call_llm(self, query, context_docs):
        """调用兼容 OpenAI Chat Completions 的接口，失败时使用本地模式。"""
        api_key = os.getenv("LLM_API_KEY", "").strip()
        api_url = os.getenv(
            "LLM_API_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        )
        model_name = os.getenv("LLM_MODEL", "qwen-plus").strip() or "qwen-plus"
        provider = os.getenv("LLM_PROVIDER", "qwen").strip() or "qwen"
        if not api_key:
            self.last_llm_status = {
                "provider": provider, "model": model_name, "configured": False,
                "active": "offline", "error": "未配置云端密钥",
            }
            return self._offline_diagnostic_fallback(
                query, context_docs, "未配置云端密钥，使用本地演示模式"
            )

        context_str = ""
        if context_docs:
            context_str = "【参考演示知识及审核案例】:\n" + "\n".join(
                f"[{index + 1}] (来源: {doc.get('source', '动态案例库')}) {doc['text']}"
                for index, doc in enumerate(context_docs)
            )
        system_prompt = (
            "你是一位工业设备检修助手。请基于给定演示资料，输出可核验的排查步骤，"
            "并明确提示现场人工确认和安全隔离。"
        )
        user_content = (
            f"{context_str}\n\n当前现场故障现象与检索词：{query}\n"
            "请给出具体排查指南，并包含参数复核建议。"
        )
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.3,
        }
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

        try:
            timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "20"))
        except ValueError:
            timeout = 20.0
        try:
            response = requests.post(api_url, json=payload, headers=headers, timeout=timeout)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty model response")
            self.last_llm_status = {
                "provider": provider, "model": model_name, "configured": True,
                "active": "qwen", "error": "",
            }
            return content.strip()
        except requests.Timeout:
            error = "请求超时"
        except requests.HTTPError as exc:
            status_code = getattr(exc.response, "status_code", None)
            error = f"接口错误 {status_code}" if status_code else "接口错误"
        except requests.RequestException:
            error = "网络请求失败"
        except (KeyError, TypeError, ValueError):
            error = "响应格式异常"
        self.last_llm_status = {
            "provider": provider, "model": model_name, "configured": True,
            "active": "offline", "error": error,
        }
        return self._offline_diagnostic_fallback(query, context_docs, error)

    def _offline_diagnostic_fallback(self, query, context_docs, error_msg):
        """网络断开、超时或未配置密钥时的本地确定性退化策略。"""
        fallback_reply = "【本地演示诊断模式】系统基于合成知识、参数规则与审核案例生成以下建议。\n\n"
        if context_docs:
            fallback_reply += "建议按“安全隔离 → 现象复核 → 参数测量 → 部件处置 → 复测签核”的顺序执行：\n\n"
            for index, doc in enumerate(context_docs, 1):
                fallback_reply += f"{index}. 依据【{doc.get('source')}】执行：{doc['text']}\n\n"
            fallback_reply += (
                "作业红线：涉及拆装、盘车、通电或压力测试时，先执行能源隔离并记录实测值；"
                "超出演示规则时暂停工单流转。"
            )
        else:
            fallback_reply += (
                "本地未检索到直接匹配的演示条目。请首先执行通用点检程序，"
                "排查连接、供能、润滑和传感器状态。"
            )
        return fallback_reply

# -*- coding: utf-8 -*-
"""轻量级本地检索与可选云端诊断服务。"""

import copy
import json
import os
import re
from pathlib import Path

import requests


class VectorService:
    """使用公开的合成知识库完成可解释检索，云端模型作为可选增强。"""

    def __init__(self):
        knowledge_path = Path(__file__).resolve().parent / "data" / "demo_knowledge_base.json"
        with knowledge_path.open("r", encoding="utf-8") as handle:
            self.knowledge_base = json.load(handle)

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
        all_docs = copy.deepcopy(self.knowledge_base)
        if dynamic_cases:
            all_docs.extend(copy.deepcopy(dynamic_cases))

        query_tokens = self._tokenize(query)
        query_set = set(query_tokens)
        scores = []
        for doc in all_docs:
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
        formatted_docs = []
        for score, doc_info in scores[:top_k]:
            doc_info["score"] = score
            doc_info["matched_terms"] = list(
                set(self._tokenize(doc_info["text"])).intersection(query_set)
            )[:8]
            formatted_docs.append(doc_info)
        return formatted_docs

    def call_llm(self, query, context_docs):
        """调用兼容 OpenAI Chat Completions 的接口，未配置时使用本地模式。"""
        api_key = os.getenv("LLM_API_KEY", "").strip()
        api_url = os.getenv(
            "LLM_API_URL",
            "https://api.openai.com/v1/chat/completions",
        )
        model_name = os.getenv("LLM_MODEL", "gpt-4o-mini")
        if not api_key:
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
            response = requests.post(api_url, json=payload, headers=headers, timeout=20)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            return self._offline_diagnostic_fallback(query, context_docs, str(exc))

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

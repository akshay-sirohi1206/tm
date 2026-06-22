"""
LLM service: routes to Bedrock direct invoke or Knowledge Base RAG
depending on whether BEDROCK_KB_ID is configured.
"""

import json
import logging
from typing import List, Optional

from services.aws_clients import (
    bedrock, bedrock_agent, AWS_REGION, BEDROCK_MODEL_ID, BEDROCK_KB_ID
)

logger = logging.getLogger("BharatBot.llm")

_SYSTEM_PROMPT = (
    "You are BharatBot, a helpful multilingual assistant. "
    "The user may write in Hindi, Marathi, English, or any mix of these. "
    "Always reply in clear, simple English only. "
    "Do not transliterate, do not mix scripts, do not switch languages in your reply."
)


def call_bedrock(user_message: str, history: Optional[List[dict]] = None) -> str:
    if BEDROCK_KB_ID:
        return _call_bedrock_kb(user_message)
    return _call_bedrock_direct(user_message, history)


def _build_messages(user_message: str, history: Optional[List[dict]]) -> list:
    messages = []
    if history:
        for entry in history:
            messages.append({"role": entry["role"], "content": entry["content"]})
    messages.append({"role": "user", "content": user_message})
    return messages


def _call_bedrock_direct(user_message: str, history: Optional[List[dict]] = None) -> str:
    logger.info(f"[LLM] InvokeModel via {BEDROCK_MODEL_ID}")
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "temperature": 0.7,
        "system": _SYSTEM_PROMPT,
        "messages": _build_messages(user_message, history),
    }
    resp = bedrock.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json",
    )
    result = json.loads(resp["body"].read())
    return result["content"][0]["text"]


def _call_bedrock_kb(user_message: str) -> str:
    logger.info(f"[RAG] Querying Knowledge Base ID: {BEDROCK_KB_ID!r}")
    resp = bedrock_agent.retrieve_and_generate(
        input={"text": user_message},
        retrieveAndGenerateConfiguration={
            "type": "KNOWLEDGE_BASE",
            "knowledgeBaseConfiguration": {
                "knowledgeBaseId": BEDROCK_KB_ID,
                "modelArn": (
                    f"arn:aws:bedrock:{AWS_REGION}::foundation-model/{BEDROCK_MODEL_ID}"
                ),
                "retrievalConfiguration": {
                    "vectorSearchConfiguration": {
                        "numberOfResults": 5,
                        "overrideSearchType": "HYBRID",
                    }
                },
                "generationConfiguration": {
                    "inferenceConfig": {
                        "textInferenceConfig": {"maxTokens": 1024, "temperature": 0.7}
                    },
                    "promptTemplate": {
                        "textPromptTemplate": (
                            "You are BharatBot, a helpful multilingual AI assistant.\n"
                            "Answer ONLY using the information in the retrieved context below.\n"
                            "If the answer is not in the context, say you don't have that information.\n\n"
                            "$search_results$\n\nQuestion: $query$"
                        )
                    },
                },
            },
        },
    )
    return resp["output"]["text"]

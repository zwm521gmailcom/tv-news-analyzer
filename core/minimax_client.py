"""
MiniMax API 客户端 — 替代 Ollama 提供 LLM 调用能力。
"""

import json
import httpx
from typing import Optional

from config import settings


async def minimax_chat(
    prompt: str,
    model: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 768,
    timeout: int = 120,
) -> str:
    """调用 MiniMax Chat API，返回纯文本响应。"""
    api_key = settings.MINIMAX_API_KEY
    if not api_key:
        raise RuntimeError("MINIMAX_API_KEY 未配置")

    model = model or settings.MINIMAX_MODEL
    base_url = settings.MINIMAX_BASE_URL

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # MiniMax v2 API 格式
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{base_url}/text/chatcompletion_v2",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

        # MiniMax 返回格式：choices[0].message.content
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "").strip()
        return ""


async def minimax_available() -> bool:
    """检查 MiniMax API 是否可用。"""
    if not settings.MINIMAX_API_KEY:
        return False
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"{settings.MINIMAX_BASE_URL}/models",
                headers={"Authorization": f"Bearer {settings.MINIMAX_API_KEY}"},
            )
            return resp.status_code == 200
    except Exception:
        return False


async def minimax_json(
    prompt: str,
    model: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 1024,
    timeout: int = 120,
) -> dict | list | None:
    """
    调用 MiniMax 并尝试解析 JSON 响应。
    优先找 [...]，再找 {...}。
    """
    try:
        response = await minimax_chat(prompt, model, temperature, max_tokens, timeout)

        # 优先查找 JSON 数组
        arr_start = response.find("[")
        arr_end = response.rfind("]") + 1
        if arr_start != -1 and arr_end > arr_start:
            candidate = response[arr_start:arr_end]
            if candidate.count("{") >= 1:
                try:
                    return json.loads(candidate)
                except Exception:
                    pass

        # 再尝试 JSON 对象
        obj_start = response.find("{")
        obj_end = response.rfind("}") + 1
        if obj_start != -1 and obj_end > obj_start:
            return json.loads(response[obj_start:obj_end])
    except Exception:
        pass
    return None

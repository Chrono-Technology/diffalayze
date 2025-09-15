#!/usr/bin/env python3

from __future__ import annotations

import json, os, re
from typing import List, Dict, Optional

import requests
try:
    import httpx
except ImportError:
    httpx = None 
try:
    import openai 
except ImportError:
    openai = None
try:
    import anthropic 
except ImportError:
    anthropic = None


__all__ = ["call_llm", "call_llm_json"]

_THINK_RE = re.compile(r"<\s*think\s*>.*?<\s*/\s*think\s*>", re.I | re.S)


def _strip_think(txt: str) -> str:
    return _THINK_RE.sub("", txt).lstrip()


def _robust_json(txt: str) -> dict:
    obj: object = txt
    for _ in range(3):
        if not isinstance(obj, str):
            break
        obj = json.loads(obj)
    if not isinstance(obj, dict):
        raise ValueError("response is not a JSON object")
    return obj


def _http_post(url: str, payload: dict, timeout: int = 600) -> dict:
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    try:
        return resp.json() 
    except ValueError:
        return json.loads(resp.text.splitlines()[-1])


def _extract(data: dict, backend: str) -> str:
    if backend in {"ollama", "openai"}:
        return (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", data.get("choices", [{}])[0].get("content", ""))
            or ""
        )
    if backend == "anthropic":
        parts = data.get("content", [])
        return "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    return ""


def call_llm(
    messages: List[Dict[str, str]],
    *,
    backend: str = "ollama",
    model: Optional[str] = None,
    temperature: float = 0.7,
    ollama_url: Optional[str] = None,
    timeout: int = 600,
) -> str:
    backend = backend.lower()
    if backend not in {"ollama", "openai", "anthropic"}:
        raise ValueError(f"Unsupported backend: {backend}")


    #-------------- Ollama --------------
    if backend == "ollama":
        base = ollama_url or os.getenv("OLLAMA_URL", "http://localhost:11434")
        url = f"{base.rstrip('/')}/v1/chat/completions"
        payload = {
            "model": model or os.getenv("OLLAMA_MODEL", "qwen3:32b"),
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        data = _http_post(url, payload, timeout)


    #-------------- OpenAI --------------
    elif backend == "openai":
        if openai is None:
            raise RuntimeError("openai package missing: pip install openai")
        key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY")
        if not key:
            raise EnvironmentError("OPENAI_API_KEY not set")
        client = openai.OpenAI(api_key=key) 
        resp = client.chat.completions.create(
            model=model or "o4-mini",
            messages=messages,
            temperature=1,
        )
        data = resp.model_dump()


    #-------------- Anthropic --------------
    else:
        if anthropic is None:
            raise RuntimeError("anthropic package missing: pip install anthropic")
        key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
        if not key:
            raise EnvironmentError("ANTHROPIC_API_KEY not set")
        client = anthropic.Anthropic(api_key=key)

        system_content: str | None = None
        if messages and messages[0]["role"] == "system":
            system_content = messages[0]["content"]
            messages = messages[1:]
        resp = client.messages.create(
            model=model or "claude-opus-4-0",
            system=system_content,
            messages=messages,
            temperature=temperature,
            max_tokens=8192,
        )
        data = resp.model_dump()

    return _strip_think(_extract(data, backend))


def call_llm_json(
    messages: List[Dict[str, str]],
    *,
    backend: str = "ollama",
    model: str | None = None,
    temperature: float = 0.7,
    **kw,
) -> dict:
    return _robust_json(call_llm(messages, backend=backend, model=model, temperature=temperature, **kw))

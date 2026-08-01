"""LLM node — calls an LLM provider (OpenAI / Anthropic / Gemini).

Uses shared client pools from ``app.clients`` so connections are reused
across node executions instead of being rebuilt every time.

Secrets are supplied via environment variables referenced as ${{env:NAME}}.
"""
from __future__ import annotations

import logging
from typing import Any

from ..clients import configure_gemini, get_anthropic_client, get_openai_client
from ..registry import BaseNode, register_node

log = logging.getLogger("aita.nodes.llm")


@register_node("llm")
class LLMNode(BaseNode):
    """Call a large language model. Returns {"text": "...", "usage": {...}}."""

    async def run(self) -> dict[str, Any]:
        provider = self.config.get("provider", "openai").lower()
        model = self.config.get("model", "gpt-4o-mini")
        api_key = self.config.get("api_key", "")
        system = self.config.get("system", "")
        user = self.config.get("user", "")
        temperature = float(self.config.get("temperature", 0.7))
        json_mode = bool(self.config.get("json_mode", False))

        if not api_key:
            raise ValueError("api_key is required (use ${{env:OPENAI_API_KEY}} in config).")
        if not user:
            raise ValueError("user prompt is required.")

        if provider == "openai":
            return await self._openai(api_key, model, system, user, temperature, json_mode)
        if provider == "anthropic":
            return await self._anthropic(api_key, model, system, user, temperature)
        if provider == "gemini":
            return await self._gemini(api_key, model, system, user, temperature)
        raise ValueError(f"Unknown provider '{provider}'. Use openai | anthropic | gemini.")

    async def _openai(self, api_key, model, system, user, temperature, json_mode) -> dict[str, Any]:
        from openai import APITimeoutError, RateLimitError
        client = get_openai_client(api_key)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        kwargs: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = await client.chat.completions.create(**kwargs)
        except APITimeoutError:
            raise RuntimeError("OpenAI API request timed out after 60s.") from None
        except RateLimitError:
            raise RuntimeError("OpenAI rate limit hit. Retry later or reduce batch size.") from None
        text = resp.choices[0].message.content or ""
        return {"text": text, "usage": _usage(resp.usage), "model": model, "provider": "openai"}

    async def _anthropic(self, api_key, model, system, user, temperature) -> dict[str, Any]:
        client = get_anthropic_client(api_key)
        resp = await client.messages.create(
            model=model,
            max_tokens=4096,
            system=system or "You are a helpful assistant.",
            messages=[{"role": "user", "content": user}],
            temperature=temperature,
        )
        text = resp.content[0].text if resp.content else ""
        return {
            "text": text,
            "usage": {"input": resp.usage.input_tokens, "output": resp.usage.output_tokens},
            "model": model,
            "provider": "anthropic",
        }

    async def _gemini(self, api_key, model, system, user, temperature) -> dict[str, Any]:
        import google.generativeai as genai
        configure_gemini(api_key)
        gm = genai.GenerativeModel(model_name=model, system_instruction=system or None)
        resp = await gm.generate_content_async(user, generation_config={"temperature": temperature})
        return {"text": resp.text or "", "usage": {}, "model": model, "provider": "gemini"}

    @classmethod
    def schema(cls) -> dict[str, Any]:
        return {
            "type": "llm",
            "label": "LLM",
            "description": "Call an LLM (OpenAI, Anthropic, or Gemini).",
            "color": "7c3aed",
            "fields": [
                {"name": "provider", "type": "select", "options": ["openai", "anthropic", "gemini"], "default": "openai"},
                {"name": "model", "type": "string", "default": "gpt-4o-mini"},
                {"name": "api_key", "type": "secret", "default": "${{env:OPENAI_API_KEY}}"},
                {"name": "system", "type": "textarea", "default": ""},
                {"name": "user", "type": "textarea", "required": True},
                {"name": "temperature", "type": "number", "default": 0.7},
                {"name": "json_mode", "type": "boolean", "default": False},
            ],
        }


def _usage(u) -> dict[str, int]:
    if not u:
        return {}
    return {"input": u.prompt_tokens, "output": u.completion_tokens, "total": u.total_tokens}

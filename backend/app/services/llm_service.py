from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel

from app.core.config import Settings, get_settings

StructuredT = TypeVar("StructuredT", bound=BaseModel)
LLMMessage = dict[str, str]


class ToolSelection(BaseModel):
    tool_name: str
    arguments: dict[str, Any]


class LLMServiceError(RuntimeError):
    def __init__(self, message: str, *, kind: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.status_code = status_code


class LLMService(Protocol):
    async def complete_structured(
        self,
        messages: Sequence[LLMMessage],
        response_model: type[StructuredT],
        *,
        system_prompt: str,
    ) -> StructuredT: ...

    def select_tool(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[dict[str, Any]],
        *,
        system_prompt: str,
    ) -> ToolSelection | None: ...

    async def stream_text(
        self,
        messages: Sequence[LLMMessage],
        *,
        system_prompt: str,
    ) -> AsyncIterator[str]: ...


class DeepSeekLLMService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.deepseek_api_key:
            raise LLMServiceError(
                "DeepSeek is not configured. Set DEEPSEEK_API_KEY in backend/.env.",
                kind="configuration",
            )

    @property
    def endpoint(self) -> str:
        return f"{self.settings.llm_base_url.rstrip('/')}/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }

    def _payload(
        self,
        messages: Sequence[LLMMessage],
        *,
        system_prompt: str,
        stream: bool,
    ) -> dict[str, Any]:
        return {
            "model": self.settings.llm_model,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "stream": stream,
        }

    async def complete_structured(
        self,
        messages: Sequence[LLMMessage],
        response_model: type[StructuredT],
        *,
        system_prompt: str,
    ) -> StructuredT:
        payload = self._payload(messages, system_prompt=system_prompt, stream=False)
        payload["response_format"] = {"type": "json_object"}
        schema = json.dumps(response_model.model_json_schema(), ensure_ascii=False)
        payload["messages"][0]["content"] += f"\n严格只返回符合此 JSON Schema 的 JSON：{schema}"
        try:
            async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds) as client:
                response = await client.post(self.endpoint, headers=self._headers(), json=payload)
                self._raise_for_status(response)
                content = response.json()["choices"][0]["message"]["content"]
            return response_model.model_validate_json(self._strip_code_fence(content))
        except LLMServiceError:
            raise
        except httpx.TimeoutException as exc:
            raise LLMServiceError("DeepSeek 请求超时，请稍后重试。", kind="timeout") from exc
        except httpx.NetworkError as exc:
            raise LLMServiceError("无法连接 DeepSeek 服务，请检查网络后重试。", kind="network") from exc
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            raise LLMServiceError("DeepSeek 返回了无法校验的结构化学习计划。", kind="invalid_response") from exc

    async def stream_text(
        self,
        messages: Sequence[LLMMessage],
        *,
        system_prompt: str,
    ) -> AsyncIterator[str]:
        payload = self._payload(messages, system_prompt=system_prompt, stream=True)
        try:
            async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds) as client:
                async with client.stream("POST", self.endpoint, headers=self._headers(), json=payload) as response:
                    self._raise_for_status(response)
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if not data or data == "[DONE]":
                            continue
                        try:
                            chunk = json.loads(data)
                            text = chunk["choices"][0]["delta"].get("content") or ""
                        except (KeyError, TypeError, json.JSONDecodeError) as exc:
                            raise LLMServiceError("DeepSeek 流式响应格式无效。", kind="invalid_response") from exc
                        if text:
                            yield text
        except LLMServiceError:
            raise
        except httpx.TimeoutException as exc:
            raise LLMServiceError("DeepSeek 流式请求超时，请稍后重试。", kind="timeout") from exc
        except httpx.NetworkError as exc:
            raise LLMServiceError("DeepSeek 流式连接中断，请检查网络后重试。", kind="network") from exc

    def select_tool(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[dict[str, Any]],
        *,
        system_prompt: str,
    ) -> ToolSelection | None:
        payload = self._payload(messages, system_prompt=system_prompt, stream=False)
        payload["tools"] = list(tools)
        payload["tool_choice"] = "auto"
        try:
            with httpx.Client(timeout=self.settings.llm_timeout_seconds) as client:
                response = client.post(self.endpoint, headers=self._headers(), json=payload)
                self._raise_for_status(response)
                message = response.json()["choices"][0]["message"]
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                return None
            if len(tool_calls) != 1:
                raise ValueError("exactly one tool call is supported per planning turn")
            function = tool_calls[0]["function"]
            arguments = json.loads(function.get("arguments") or "{}")
            if not isinstance(arguments, dict):
                raise ValueError("tool arguments must be an object")
            return ToolSelection(tool_name=function["name"], arguments=arguments)
        except LLMServiceError:
            raise
        except httpx.TimeoutException as exc:
            raise LLMServiceError("DeepSeek 工具选择请求超时，请稍后重试。", kind="timeout") from exc
        except httpx.NetworkError as exc:
            raise LLMServiceError("无法连接 DeepSeek 工具选择服务。", kind="network") from exc
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LLMServiceError("DeepSeek 返回了无效的工具调用。", kind="invalid_response") from exc
    @staticmethod
    def _strip_code_fence(content: str) -> str:
        stripped = content.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            return "\n".join(lines[1:-1]).strip()
        return stripped

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        if response.status_code in {401, 403}:
            message, kind = "DeepSeek 认证失败，请检查本地 API Key 配置。", "authentication"
        elif response.status_code == 429:
            message, kind = "DeepSeek 请求过于频繁或额度受限，请稍后重试。", "rate_limit"
        elif response.status_code >= 500:
            message, kind = "DeepSeek 服务暂时不可用，请稍后重试。", "provider"
        else:
            message, kind = "DeepSeek 请求失败，请检查模型和接口配置。", "provider"
        raise LLMServiceError(message, kind=kind, status_code=response.status_code)


class FakeLLMService:
    """Deterministic injectable fake used by automated tests; it never performs I/O."""

    def __init__(self) -> None:
        self.calls: list[list[LLMMessage]] = []

    async def complete_structured(
        self,
        messages: Sequence[LLMMessage],
        response_model: type[StructuredT],
        *,
        system_prompt: str,
    ) -> StructuredT:
        self.calls.append(list(messages))
        latest = next((item["content"] for item in reversed(messages) if item["role"] == "user"), "")
        if response_model.__name__ == "RagQueryPlan":
            users = [item["content"] for item in messages if item["role"] == "user"]
            standalone = f"{users[-2]}；{latest}" if len(users) > 1 and any(word in latest for word in ("这个", "继续", "那")) else latest
            parts = [part.strip() for part in standalone.replace("？", "；").split("；") if part.strip()]
            return response_model.model_validate({"retrieval_required": True, "standalone_query": standalone, "subqueries": parts if len(parts) > 1 else [], "hyde_passages": [f"专业资料可能说明：{standalone}"]})
        from app.agents.learning import build_learning_plan, parse_learning_request
        return response_model.model_validate(build_learning_plan(parse_learning_request(latest)))

    def select_tool(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[dict[str, Any]],
        *,
        system_prompt: str,
    ) -> ToolSelection | None:
        self.calls.append(list(messages))
        latest = next((item["content"] for item in reversed(messages) if item["role"] == "user"), "")
        lower = latest.lower()
        scored: list[tuple[int, dict[str, Any]]] = []
        for definition in tools:
            function = definition.get("function") or {}
            searchable = f'{function.get("name", "")} {function.get("description", "")}'.lower()
            score = 0
            keyword_groups = (
                (("转换", "换算", "convert"), ("convert_time",)),
                (("几点", "时间", "现在", "time"), ("get_current_time", "current_time")),
                (("天气", "weather"), ("weather",)),
                (("邮件", "发送", "email"), ("email", "send")),
            )
            for request_words, tool_words in keyword_groups:
                if any(word in lower for word in request_words) and any(word in searchable for word in tool_words):
                    score += 10
            if score:
                scored.append((score, function))
        if not scored:
            return None
        function = max(scored, key=lambda item: item[0])[1]
        schema = function.get("parameters") or {}
        properties = schema.get("properties") if isinstance(schema, dict) else {}
        properties = properties if isinstance(properties, dict) else {}
        zones = re.findall(r"[A-Za-z_]+/[A-Za-z_]+", latest)
        arguments: dict[str, Any] = {}
        for key, property_schema in properties.items():
            if not isinstance(property_schema, dict):
                continue
            if key in {"timezone", "source_timezone"}:
                arguments[key] = zones[0] if zones else "Asia/Shanghai"
            elif key == "target_timezone":
                arguments[key] = zones[1] if len(zones) > 1 else "UTC"
            elif key == "time":
                match = re.search(r"\b\d{1,2}:\d{2}\b", latest)
                arguments[key] = match.group(0) if match else "09:00"
            elif key in {"query", "q", "message", "text", "prompt"}:
                arguments[key] = latest
        return ToolSelection(tool_name=str(function["name"]), arguments=arguments)
    async def stream_text(
        self,
        messages: Sequence[LLMMessage],
        *,
        system_prompt: str,
    ) -> AsyncIterator[str]:
        self.calls.append(list(messages))
        users = [item["content"] for item in messages if item["role"] == "user"]
        if "学习计划" in system_prompt:
            text = "这是由 FakeLLM 生成并校验的学习计划回复。"
        elif "只能依据下列证据" in system_prompt:
            text = "依据知识库，建议循序渐进并优先保证动作标准。[1]" if "证据：\n" in system_prompt else "当前证据不足，无法给出有引用依据的训练建议。"
        elif len(users) > 1:
            text = f"我记得你上一轮说过：{users[-2]}。现在回答：{users[-1]}"
        else:
            text = f"FakeLLM 回复：{users[-1] if users else ''}"
        for chunk in (text[index : index + 4] for index in range(0, len(text), 4)):
            yield chunk

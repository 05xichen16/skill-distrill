from __future__ import annotations

import asyncio
import http.client
import json
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from source.runtime.env_config import ModelConfig


class _RetryableGatewayError(Exception):
    """Transient gateway error worth retrying (5xx / timeout / connection drop)."""


@dataclass
class ChatCompletionClient:
    config: ModelConfig

    async def create(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        response_format: dict[str, Any] | None = None,
        enable_thinking: bool | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._create_sync,
            messages=messages,
            tools=tools or [],
            tool_choice=tool_choice,
            response_format=response_format,
            enable_thinking=enable_thinking,
        )

    def _create_sync(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str,
        response_format: dict[str, Any] | None,
        enable_thinking: bool | None,
    ) -> dict[str, Any]:
        if not self.config.is_configured():
            raise RuntimeError("Model gateway is not configured. Check .env.")

        think = self.config.enable_thinking if enable_thinking is None else enable_thinking
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "stream": self.config.stream,
            # enable_thinking is read from chat_template_kwargs by the contest gateway.
            "chat_template_kwargs": {"enable_thinking": think},
        }
        if self.config.max_tokens > 0:
            payload["max_tokens"] = self.config.max_tokens
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        if response_format:
            payload["response_format"] = response_format

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        # The task spec is internally inconsistent about the header name
        # (package_id vs packageId); send both so token accounting always binds.
        if self.config.package_id:
            headers["package_id"] = self.config.package_id
            headers["packageId"] = self.config.package_id

        attempts = max(1, self.config.max_retries + 1)
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                data = self._attempt_post(body=body, headers=headers)
                result = self._parse_response(data)
                self._log_usage(result)
                return result
            except _RetryableGatewayError as exc:
                last_error = exc
                if attempt < attempts:
                    delay = self.config.retry_backoff * (2 ** (attempt - 1))
                    print(
                        f"model gateway transient error (attempt {attempt}/{attempts}), "
                        f"retry in {delay:.1f}s: {exc}",
                        file=sys.stderr,
                    )
                    time.sleep(delay)
                    continue
                raise RuntimeError(f"Model gateway failed after {attempts} attempts: {exc}") from exc

        raise RuntimeError(f"Model gateway failed: {last_error}")

    def _attempt_post(self, *, body: bytes, headers: dict[str, str]) -> str:
        request = urllib.request.Request(
            self.config.chat_completions_url,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                return response.read().decode("utf-8")
        except http.client.RemoteDisconnected as exc:
            try:
                return self._post_with_http_client(body=body, headers=headers)
            except Exception as inner:  # fall back failed too -> retry whole attempt
                raise _RetryableGatewayError(f"remote disconnected: {inner}") from exc
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code >= 500:
                raise _RetryableGatewayError(f"HTTP {exc.code}: {detail}") from exc
            raise RuntimeError(f"Model gateway HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
            raise _RetryableGatewayError(f"connection failed: {exc}") from exc

    def _log_usage(self, result: dict[str, Any]) -> None:
        usage = result.get("usage")
        if isinstance(usage, dict):
            prompt = usage.get("prompt_tokens")
            completion = usage.get("completion_tokens")
            total = usage.get("total_tokens")
            print(
                f"token usage: prompt={prompt} completion={completion} total={total}",
                file=sys.stderr,
            )

    def _post_with_http_client(self, *, body: bytes, headers: dict[str, str]) -> str:
        parsed = urllib.parse.urlparse(self.config.chat_completions_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise RuntimeError(f"Unsupported model gateway URL: {self.config.chat_completions_url}")

        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        connection_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        connection = connection_cls(parsed.hostname, parsed.port, timeout=self.config.timeout_seconds)
        try:
            connection.request("POST", path, body=body, headers=headers)
            response = connection.getresponse()
            data = response.read().decode("utf-8", errors="replace")
        finally:
            connection.close()

        if response.status >= 400:
            raise RuntimeError(f"Model gateway HTTP {response.status}: {data}")
        return data

    def _parse_response(self, data: str) -> dict[str, Any]:
        try:
            return json.loads(data)
        except json.JSONDecodeError as exc:
            if self._looks_like_sse(data):
                return self._parse_sse_response(data)
            raise RuntimeError(f"Model gateway returned non-JSON response: {data[:500]}") from exc

    def _looks_like_sse(self, data: str) -> bool:
        stripped = data.lstrip()
        return stripped.startswith("data:") or "\ndata:" in data

    def _parse_sse_response(self, data: str) -> dict[str, Any]:
        role = "assistant"
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}
        finish_reason = None
        completion_id = "streamed"
        model = self.config.model
        created = None
        usage: dict[str, Any] | None = None

        for line in data.splitlines():
            line = line.strip()
            if not line or not line.startswith("data:"):
                continue
            payload_text = line[len("data:") :].strip()
            if not payload_text or payload_text == "[DONE]":
                continue
            try:
                chunk = json.loads(payload_text)
            except json.JSONDecodeError:
                continue

            completion_id = chunk.get("id") or completion_id
            model = chunk.get("model") or model
            created = chunk.get("created", created)
            if isinstance(chunk.get("usage"), dict):
                usage = chunk["usage"]
            choices = chunk.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            finish_reason = choice.get("finish_reason") or finish_reason
            delta = choice.get("delta") or choice.get("message") or {}
            if not isinstance(delta, dict):
                continue

            role = delta.get("role") or role
            content = delta.get("content")
            if isinstance(content, str):
                content_parts.append(content)
            reasoning = delta.get("reasoning") or delta.get("reasoning_content")
            if isinstance(reasoning, str):
                reasoning_parts.append(reasoning)

            for raw_tool_call in delta.get("tool_calls") or []:
                if not isinstance(raw_tool_call, dict):
                    continue
                index = int(raw_tool_call.get("index", len(tool_calls)))
                current = tool_calls.setdefault(
                    index,
                    {
                        "id": raw_tool_call.get("id") or f"stream_tool_call_{index}",
                        "type": raw_tool_call.get("type") or "function",
                        "function": {"name": "", "arguments": ""},
                    },
                )
                if raw_tool_call.get("id"):
                    current["id"] = raw_tool_call["id"]
                if raw_tool_call.get("type"):
                    current["type"] = raw_tool_call["type"]

                raw_function = raw_tool_call.get("function") or {}
                if raw_function.get("name"):
                    current["function"]["name"] += raw_function["name"]
                if raw_function.get("arguments"):
                    current["function"]["arguments"] += raw_function["arguments"]

            function_call = delta.get("function_call")
            if isinstance(function_call, dict):
                current = tool_calls.setdefault(
                    0,
                    {
                        "id": "legacy_function_call",
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    },
                )
                if function_call.get("name"):
                    current["function"]["name"] += function_call["name"]
                if function_call.get("arguments"):
                    current["function"]["arguments"] += function_call["arguments"]

        message: dict[str, Any] = {
            "role": role,
            "content": "".join(content_parts),
        }
        if reasoning_parts:
            message["reasoning_content"] = "".join(reasoning_parts)
        if tool_calls:
            message["tool_calls"] = [tool_calls[index] for index in sorted(tool_calls)]

        result: dict[str, Any] = {
            "id": completion_id,
            "created": created,
            "model": model,
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": finish_reason,
                }
            ],
        }
        if usage is not None:
            result["usage"] = usage
        return result


def first_message(completion: dict[str, Any]) -> dict[str, Any]:
    choices = completion.get("choices") or []
    if not choices:
        raise RuntimeError(f"Model gateway returned no choices: {completion}")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise RuntimeError(f"Model gateway returned invalid message: {completion}")
    return message

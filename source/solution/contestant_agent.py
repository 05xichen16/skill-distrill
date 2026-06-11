from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path
from typing import Any

from source.runtime.env_config import ModelConfig, env_bool, env_int, load_dotenv
from source.runtime.agent_context import AgentContext
from source.runtime.openai_chat_client import ChatCompletionClient, first_message


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


SYSTEM_PROMPT = """
你是 skill 蒸馏攻防 Agent 大赛的参赛 Agent。

你需要解决赛方给出的题目。可用 MCP-style tools、skills 和 sub-agents 来自当前参赛 solution 的自动发现结果。
题目本身不会指定你应该使用哪个 MCP-style tool、skill 或 sub-agent；是否使用、使用哪个、如何编排，都由你自己决定。
文件内容不会自动进入上下文；需要读取题目声明的文件或目录内文件时，调用 text_read_file。
如果需要使用某个 skill，先调用 skill_load 读取完整 SKILL.md，再按其中说明决定是否 skill_read_resource 或 skill_run。
如果需要复核，可以调用 agent_delegate。

最终只输出题目要求的答案正文。不要输出思考过程、markdown、代码块、<think> 标签、结果对象或额外元数据字段。
""".strip()


class ContestantAgent:
    """Contestant-editable main agent entrypoint."""

    async def solve(self, *, question: dict[str, Any], context: AgentContext) -> str:
        load_dotenv()
        if not env_bool("AGENT_DEMO_USE_LLM", True):
            raise RuntimeError("AGENT_DEMO_USE_LLM is disabled; configure a model gateway or implement ContestantAgent.solve().")

        # 参赛者主要改这里：
        # - question 是赛方运行器传入的公开题面对象，包含 id/question/title/explanation/files 等可见字段。
        # - question["files"] 是本题允许读取的文件或目录列表，文本内容不会自动进入上下文（需 text_read_file）。
        # - 图片附件会在这里自动 base64 注入为 image_url 块，让多模态模型直接看到。
        # - context 提供当前 solution 自动发现到的 MCP tools、skills、sub-agents 以及 call_tool(...) 调用入口。
        text_prompt = json.dumps(
            {
                "question": question,
                "files": question.get("files") or [],
                "available_tools": context.available_tools,
                "available_skills": context.available_skills,
                "available_sub_agents": context.available_agents,
                "tool_usage": "Call tools only when useful. Declared images are already attached; use text_read_file to read declared text files; use skill_load before skill_run; use agent_delegate for sub-agents.",
                "final_output": "Return only the final answer text.",
            },
            ensure_ascii=False,
            indent=2,
        )
        user_content = self._compose_content(text_prompt, self._image_blocks(context))
        enable_thinking = self._should_enable_thinking(question)

        try:
            return await self._run_model_loop(
                system_prompt=SYSTEM_PROMPT,
                user_content=user_content,
                context=context,
                enable_thinking=enable_thinking,
            )
        except Exception as exc:  # last-resort safety net: never return an empty answer
            print(f"agent loop failed, falling back to direct answer: {exc}", file=sys.stderr)
            return await self._direct_answer(user_content, enable_thinking=enable_thinking)

    def _should_enable_thinking(self, question: dict[str, Any]) -> bool:
        """Routing hook for the thinking/token trade-off.

        Phase A keeps thinking on for correctness (token is only a tiebreaker).
        Phase B can branch here per question type/level to win the token
        tiebreak without risking correctness.
        """

        return env_bool("AGENT_DEMO_ENABLE_THINKING", True)

    def _iter_image_files(self, context: AgentContext):
        for raw in context.allowed_file_paths:
            path = Path(raw)
            if path.is_dir():
                for child in sorted(path.rglob("*")):
                    if child.is_file() and child.suffix.lower() in IMAGE_EXTENSIONS:
                        yield child
            elif path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                yield path

    def _image_blocks(self, context: AgentContext) -> list[dict[str, Any]]:
        # Safety caps: a directory file may resolve to many images (e.g. a
        # training/validation folder). Bound count and total bytes so a single
        # request can't blow up context or token cost; log when we truncate.
        max_images = env_int("AGENT_DEMO_MAX_IMAGES", 6)
        max_total_bytes = max(1, env_int("AGENT_DEMO_MAX_IMAGE_MB", 12)) * 1024 * 1024
        all_images = list(self._iter_image_files(context))
        blocks: list[dict[str, Any]] = []
        total_bytes = 0
        for path in all_images:
            if len(blocks) >= max_images:
                break
            try:
                raw = path.read_bytes()
            except OSError as exc:
                print(f"failed to read image {path}: {exc}", file=sys.stderr)
                continue
            if blocks and total_bytes + len(raw) > max_total_bytes:
                break
            total_bytes += len(raw)
            mime = IMAGE_MIME_TYPES.get(path.suffix.lower(), "image/png")
            encoded = base64.b64encode(raw).decode("ascii")
            blocks.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{encoded}"},
                }
            )
        if len(all_images) > len(blocks):
            print(
                f"attached {len(blocks)}/{len(all_images)} declared images "
                f"(cap: AGENT_DEMO_MAX_IMAGES={max_images}, "
                f"AGENT_DEMO_MAX_IMAGE_MB={max_total_bytes // (1024 * 1024)})",
                file=sys.stderr,
            )
        return blocks

    def _compose_content(self, text: str, images: list[dict[str, Any]]):
        if images:
            return [{"type": "text", "text": text}, *images]
        return text

    def _split_user_content(self, user_content) -> tuple[str, list[dict[str, Any]]]:
        if isinstance(user_content, str):
            return user_content, []
        text_parts: list[str] = []
        images: list[dict[str, Any]] = []
        for block in user_content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text_parts.append(str(block.get("text") or ""))
            elif block.get("type") == "image_url":
                images.append(block)
        return "\n".join(text_parts), images

    async def _direct_answer(self, user_content, *, enable_thinking: bool) -> str:
        config = ModelConfig.from_env()
        client = ChatCompletionClient(config)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        completion = await client.create(
            messages=messages,
            tools=[],
            tool_choice="none",
            enable_thinking=enable_thinking,
        )
        return self._clean_final_answer(str(first_message(completion).get("content") or ""))

    async def _run_model_loop(self, *, system_prompt: str, user_content, context: AgentContext, enable_thinking: bool) -> str:
        if not env_bool("AGENT_DEMO_NATIVE_TOOLS", True):
            return await self._run_json_tool_loop(system_prompt=system_prompt, user_content=user_content, context=context, enable_thinking=enable_thinking)

        try:
            return await self._run_native_tool_loop(system_prompt=system_prompt, user_content=user_content, context=context, enable_thinking=enable_thinking)
        except Exception:
            if env_bool("AGENT_DEMO_JSON_TOOL_FALLBACK", True):
                try:
                    return await self._run_json_tool_loop(system_prompt=system_prompt, user_content=user_content, context=context, enable_thinking=enable_thinking)
                except Exception:
                    pass
            raise

    async def _run_native_tool_loop(self, *, system_prompt: str, user_content, context: AgentContext, enable_thinking: bool) -> str:
        config = ModelConfig.from_env()
        client = ChatCompletionClient(config)
        tools = await context.mcp.list_openai_tools(
            allowed_tools=context.allowed_tools,
            allowed_agents=context.allowed_agents,
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        max_iter = env_int("AGENT_DEMO_MAX_ITER", 6)
        for step in range(1, max_iter + 1):
            completion = await client.create(messages=messages, tools=tools, tool_choice="auto", enable_thinking=enable_thinking)
            message = first_message(completion)
            tool_calls = self._tool_calls_from_message(message)
            content = str(message.get("content") or "")

            messages.append(self._assistant_message_for_history(message))
            if not tool_calls:
                if content.strip():
                    return self._clean_final_answer(content)
                messages.append({"role": "user", "content": "请输出最终答案文本。"})
                continue

            for tool_call in tool_calls:
                tool_name = self._tool_call_name(tool_call)
                args_text = self._tool_call_arguments(tool_call)
                try:
                    tool_args = json.loads(args_text)
                except json.JSONDecodeError:
                    tool_args = {}
                tool_result = await self._call_tool_as_text(context, tool_name, tool_args)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id", ""),
                        "name": tool_name,
                        "content": tool_result[:12000],
                    }
                )

        messages.append({"role": "user", "content": "请停止调用工具，直接输出最终答案文本。"})
        completion = await client.create(messages=messages, tools=[], tool_choice="none", enable_thinking=enable_thinking)
        return self._clean_final_answer(str(first_message(completion).get("content") or ""))

    async def _run_json_tool_loop(self, *, system_prompt: str, user_content, context: AgentContext, enable_thinking: bool) -> str:
        """Prompt-level JSON tool loop for gateways that reject native tools."""

        config = ModelConfig.from_env()
        client = ChatCompletionClient(config)
        tools = await context.mcp.list_openai_tools(
            allowed_tools=context.allowed_tools,
            allowed_agents=context.allowed_agents,
        )
        tool_specs = [
            {
                "name": tool["function"]["name"],
                "description": tool["function"].get("description", ""),
                "parameters": tool["function"].get("parameters", {}),
            }
            for tool in tools
        ]
        json_tool_prompt = (
            system_prompt
            + "\n\n当前模型网关可能不支持原生 tools 字段。"
            + "\n需要工具时，只输出 JSON，且第一个字符必须是 {，不要输出 markdown 代码块或思考过程："
            + '{"tool_calls":[{"name":"工具名","arguments":{}}]}'
            + "\n任务完成时，直接输出最终答案文本；不要包成结果对象。"
        )

        prompt_text, images = self._split_user_content(user_content)
        first_user_text = json.dumps(
            {
                "prompt": prompt_text,
                "available_tools": tool_specs,
                "instruction": "如果需要工具，只输出 tool_calls JSON；如果不需要工具，直接输出最终答案文本。",
            },
            ensure_ascii=False,
            indent=2,
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": json_tool_prompt},
            {"role": "user", "content": self._compose_content(first_user_text, images)},
        ]

        max_iter = env_int("AGENT_DEMO_MAX_ITER", 6)
        for step in range(1, max_iter + 1):
            completion = await client.create(messages=messages, tools=[], tool_choice="none", enable_thinking=enable_thinking)
            content = str(first_message(completion).get("content") or "").strip()

            parsed = self._parse_json_object(content)
            tool_calls = self._json_prompt_tool_calls(parsed) if parsed else None
            if not tool_calls:
                if content:
                    return self._clean_final_answer(content)
                messages.append({"role": "user", "content": "请输出最终答案文本，或输出 tool_calls JSON。"})
                continue

            tool_results = []
            for call_index, tool_call in enumerate(tool_calls):
                if not isinstance(tool_call, dict):
                    continue
                tool_name = str(tool_call.get("name") or tool_call.get("tool") or "")
                tool_args = tool_call.get("arguments")
                if tool_args is None:
                    tool_args = {
                        key: value
                        for key, value in tool_call.items()
                        if key not in {"name", "tool"}
                    }
                if not isinstance(tool_args, dict):
                    tool_args = {}
                tool_results.append(
                    {
                        "index": call_index,
                        "name": tool_name,
                        "result": await self._call_tool_as_text(context, tool_name, tool_args),
                    }
                )

            messages.append({"role": "assistant", "content": content})
            messages.append(
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "tool_results": tool_results,
                            "instruction": "根据工具结果继续。还需要工具则输出 tool_calls JSON；完成则直接输出最终答案文本。",
                        },
                        ensure_ascii=False,
                        indent=2,
                    )[:16000],
                }
            )

        messages.append({"role": "user", "content": "请停止请求工具，直接输出最终答案文本。"})
        completion = await client.create(messages=messages, tools=[], tool_choice="none", enable_thinking=enable_thinking)
        return self._clean_final_answer(str(first_message(completion).get("content") or ""))

    async def _call_tool_as_text(self, context: AgentContext, tool_name: str, tool_args: dict[str, Any]) -> str:
        try:
            tool_result = await context.call_tool(tool_name, tool_args)
        except Exception as exc:
            tool_result = f"工具调用失败：{exc}"
        if isinstance(tool_result, str):
            return tool_result
        return json.dumps(tool_result, ensure_ascii=False)

    def _assistant_message_for_history(self, message: dict[str, Any]) -> dict[str, Any]:
        history_message: dict[str, Any] = {
            "role": "assistant",
            "content": message.get("content") or "",
        }
        tool_calls = self._tool_calls_from_message(message)
        if tool_calls:
            history_message["tool_calls"] = tool_calls
        return history_message

    def _tool_calls_from_message(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            normalized = []
            for tool_call in tool_calls:
                if isinstance(tool_call.get("function"), dict):
                    normalized.append(tool_call)
                else:
                    normalized.append(
                        {
                            "id": tool_call.get("id", ""),
                            "type": tool_call.get("type", "function"),
                            "function": {
                                "name": tool_call.get("name", ""),
                                "arguments": tool_call.get("arguments") or "{}",
                            },
                        }
                    )
            return normalized
        function_call = message.get("function_call")
        if isinstance(function_call, dict):
            return [
                {
                    "id": "legacy_function_call",
                    "type": "function",
                    "function": {
                        "name": function_call.get("name", ""),
                        "arguments": function_call.get("arguments") or "{}",
                    },
                }
            ]
        return []

    def _tool_call_name(self, tool_call: dict[str, Any]) -> str:
        if isinstance(tool_call.get("function"), dict):
            return str(tool_call["function"].get("name") or "")
        return str(tool_call.get("name") or "")

    def _tool_call_arguments(self, tool_call: dict[str, Any]) -> str:
        if isinstance(tool_call.get("function"), dict):
            return str(tool_call["function"].get("arguments") or "{}")
        return str(tool_call.get("arguments") or "{}")

    def _parse_json_object(self, content: str) -> dict[str, Any] | None:
        text = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        candidates = [text]
        candidates.extend(match.group(1).strip() for match in re.finditer(r"```(?:json|tool_calls)?\s*(.*?)```", text, flags=re.DOTALL))
        object_match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if object_match:
            candidates.append(object_match.group(0))
        array_match = re.search(r"\[.*\]", text, flags=re.DOTALL)
        if array_match:
            candidates.append(array_match.group(0))

        for candidate in candidates:
            try:
                data = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
            if isinstance(data, list):
                return {"tool_calls": data}
        return None

    def _clean_final_answer(self, content: str) -> str:
        cleaned = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        # Drop a dangling unclosed reasoning block if the model only emitted <think>.
        cleaned = re.sub(r"<think>.*\Z", "", cleaned, flags=re.DOTALL).strip()
        cleaned = self._strip_markdown_fence(cleaned)
        cleaned = self._strip_answer_prefix(cleaned)
        cleaned = self._strip_wrapping_quotes(cleaned)
        return cleaned or content.strip()

    def _strip_markdown_fence(self, text: str) -> str:
        match = re.fullmatch(r"```[a-zA-Z0-9_]*\n(.*?)\n?```", text, flags=re.DOTALL)
        if match:
            return match.group(1).strip()
        return text

    def _strip_answer_prefix(self, text: str) -> str:
        # Remove a single leading label like "答案：" / "最终答案:" / "Answer:" if present.
        pattern = r"^\s*(?:最终答案|最终结果|答案|结果|回答|Answer|Final Answer|Result)\s*[:：]\s*"
        stripped = re.sub(pattern, "", text, count=1, flags=re.IGNORECASE)
        return stripped.strip()

    def _strip_wrapping_quotes(self, text: str) -> str:
        pairs = {'"': '"', "'": "'", "“": "”", "‘": "’", "「": "」", "『": "』"}
        if len(text) >= 2 and text[0] in pairs and text[-1] == pairs[text[0]]:
            inner = text[1:-1].strip()
            # Only unwrap when the quotes are truly enclosing (no same quote inside).
            if text[0] not in inner and pairs[text[0]] not in inner:
                return inner
        return text

    def _json_prompt_tool_calls(self, parsed: dict[str, Any]) -> list[dict[str, Any]] | None:
        tool_calls = parsed.get("tool_calls")
        if isinstance(tool_calls, list):
            return tool_calls
        if parsed.get("tool") or (parsed.get("name") and "arguments" in parsed):
            return [parsed]
        return None

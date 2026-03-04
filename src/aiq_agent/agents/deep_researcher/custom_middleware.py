# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Custom middleware for the deep research agent."""

import json
import logging

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage
from langchain_core.messages import ToolMessage

logger = logging.getLogger(__name__)


class EmptyContentFixMiddleware(AgentMiddleware):
    """
    Middleware that fixes empty ToolMessage content.

    Some LLM APIs (e.g., NVIDIA, OpenAI) reject messages with empty content.
    This middleware ensures all ToolMessages have non-empty content by
    replacing empty strings with a placeholder.
    """

    def __init__(self, placeholder: str = "empty content received."):
        """
        Initialize the middleware.

        Args:
            placeholder: Text to use when ToolMessage content is empty.
        """
        self.placeholder = placeholder

    async def awrap_model_call(self, request, handler):
        """Fix empty ToolMessage content before sending to the model."""
        fixed_messages = []
        for msg in request.messages:
            if isinstance(msg, ToolMessage) and not msg.content:
                # Create a new ToolMessage with placeholder content
                fixed_messages.append(
                    ToolMessage(
                        content=self.placeholder,
                        tool_call_id=msg.tool_call_id,
                        name=getattr(msg, "name", None),
                        id=msg.id,
                    )
                )
            else:
                fixed_messages.append(msg)

        return await handler(request.override(messages=fixed_messages))


# Parameter name aliases: keys are substrings matched against tool names
_PARAM_ALIASES: dict[str, dict[str, str]] = {
    "search": {"question": "query"},  # Any tool with "search" in the name
}

# Common hallucinated tool name mappings
_TOOL_NAME_ALIASES: dict[str, str] = {
    "open_file": "read_file",
    "find": "grep",
    "find_file": "glob",
    # Claude Opus 4.6 hallucinations
    "advance_web_search_tool": "advanced_web_search_tool",
    "web_search": "advanced_web_search_tool",
    "search_web": "advanced_web_search_tool",
    "core_web_search": "advanced_web_search_tool",
    "search": "advanced_web_search_tool",
    # Common typo hallucinations
    "todos": "write_todos",
    "tink": "think",
}


class ToolNameSanitizationMiddleware(AgentMiddleware):
    """
    Middleware that sanitizes corrupted tool names in LLM responses.

    LLMs sometimes generate malformed tool calls with suffixes like
    <|channel|>commentary or .exec, or hallucinate tool names like
    open_file or find. This middleware intercepts the model response
    and fixes tool names before the framework dispatches them.
    """

    def __init__(self, valid_tool_names: list[str]):
        self.valid_tool_names = set(valid_tool_names)

    def _sanitize_tool_name(self, name: str) -> str:
        """Sanitize a potentially corrupted tool name.

        Returns the cleaned name if it maps to a valid tool,
        otherwise returns the original name unchanged.
        """
        # 0. Convert kebab-case to snake_case if the result is valid
        if "-" in name:
            candidate = name.replace("-", "_")
            if candidate in self.valid_tool_names:
                logger.info("Sanitized kebab-case tool name: '%s' -> '%s'", name, candidate)
                return candidate

        # 1. Strip <|channel|> and everything after
        if "<|channel|>" in name:
            candidate = name.split("<|channel|>")[0]
            if candidate in self.valid_tool_names:
                logger.info("Sanitized tool name: '%s' -> '%s'", name, candidate)
                return candidate

        # 2. Strip dot suffix if base name is valid
        if "." in name:
            candidate = name.split(".")[0]
            if candidate in self.valid_tool_names:
                logger.info("Sanitized tool name: '%s' -> '%s'", name, candidate)
                return candidate

        # 3. Map common hallucinated names
        if name in _TOOL_NAME_ALIASES:
            mapped = _TOOL_NAME_ALIASES[name]
            if mapped in self.valid_tool_names:
                logger.info("Mapped tool name: '%s' -> '%s'", name, mapped)
                return mapped

        return name

    def _sanitize_tool_args(self, tool_name: str, args: dict) -> dict:
        """Fix common parameter name mistakes based on tool name patterns."""
        for pattern, aliases in _PARAM_ALIASES.items():
            if pattern in tool_name:
                for wrong_name, right_name in aliases.items():
                    if wrong_name in args and right_name not in args:
                        args = {right_name if k == wrong_name else k: v for k, v in args.items()}
                        logger.info("Sanitized param name in '%s': '%s' -> '%s'", tool_name, wrong_name, right_name)
        return args

    async def awrap_model_call(self, request, handler):
        """Intercept model response and sanitize tool names and args."""
        response = await handler(request)

        needs_fix = False
        for msg in response.result:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    if self._sanitize_tool_name(tc["name"]) != tc["name"]:
                        needs_fix = True
                        break
                    if self._sanitize_tool_args(tc["name"], tc["args"]) != tc["args"]:
                        needs_fix = True
                        break
                if needs_fix:
                    break

        if not needs_fix:
            return response

        new_result = []
        for msg in response.result:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                new_tool_calls = []
                for tc in msg.tool_calls:
                    sanitized_name = self._sanitize_tool_name(tc["name"])
                    sanitized_args = self._sanitize_tool_args(sanitized_name, tc["args"])
                    new_tool_calls.append({**tc, "name": sanitized_name, "args": sanitized_args})
                new_msg = AIMessage(
                    content=msg.content,
                    tool_calls=new_tool_calls,
                    id=msg.id,
                )
                new_result.append(new_msg)
            else:
                new_result.append(msg)

        return ModelResponse(result=new_result, structured_response=response.structured_response)


# Fuzzy status value mapping for write_todos
_STATUS_ALIASES: dict[str, str] = {
    "complete": "completed",
    "done": "completed",
    "finished": "completed",
    "progress": "in_progress",
    "in progress": "in_progress",
    "partial": "in_progress",
    "todo": "pending",
    "not_started": "pending",
}


class TodoSanitizationMiddleware(AgentMiddleware):
    """Middleware that fixes malformed write_todos arguments before Pydantic validation.

    Handles: wrong status enum values, missing/wrong field names,
    JSON string instead of list, and extra fields.
    """

    def _sanitize_todo_item(self, item: dict) -> dict:
        """Fix a single todo item."""
        fixed = {}

        # Map 'context' → 'content'
        if "context" in item and "content" not in item:
            fixed["content"] = item["context"]
        elif "content" in item:
            fixed["content"] = item["content"]
        else:
            fixed["content"] = str(item.get("text", item.get("description", "untitled task")))

        # Fix status enum
        raw_status = str(item.get("status", "pending")).lower().strip()
        fixed["status"] = _STATUS_ALIASES.get(raw_status, raw_status)
        # If still invalid after alias lookup, default to pending
        if fixed["status"] not in ("pending", "in_progress", "completed"):
            logger.info("Invalid todo status '%s', defaulting to 'pending'", raw_status)
            fixed["status"] = "pending"

        return fixed

    def _sanitize_todos_args(self, args: dict) -> dict:
        """Fix write_todos arguments."""
        todos = args.get("todos")
        if todos is None:
            return args

        # Handle JSON string instead of list
        if isinstance(todos, str):
            try:
                # Strip any channel markers that leaked in
                cleaned = todos.split("<|")[0] if "<|" in todos else todos
                todos = json.loads(cleaned)
            except (json.JSONDecodeError, ValueError):
                logger.warning("Could not parse write_todos string arg")
                return args

        if not isinstance(todos, list):
            return args

        fixed_todos = [self._sanitize_todo_item(item) for item in todos if isinstance(item, dict)]
        return {**args, "todos": fixed_todos}

    async def awrap_model_call(self, request, handler):
        """Intercept model response and sanitize write_todos args."""
        response = await handler(request)

        needs_fix = False
        for msg in response.result:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc["name"] == "write_todos":
                        needs_fix = True
                        break

        if not needs_fix:
            return response

        new_result = []
        for msg in response.result:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                new_tool_calls = []
                for tc in msg.tool_calls:
                    if tc["name"] == "write_todos":
                        new_tool_calls.append({**tc, "args": self._sanitize_todos_args(tc["args"])})
                    else:
                        new_tool_calls.append(tc)
                new_msg = AIMessage(content=msg.content, tool_calls=new_tool_calls, id=msg.id)
                new_result.append(new_msg)
            else:
                new_result.append(msg)

        return ModelResponse(result=new_result, structured_response=response.structured_response)

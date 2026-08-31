import json
from dataclasses import dataclass

from .llm import LLMClient
from .memory import SlidingWindowMemory
from .tool import ToolRegistry
from .tracer import ExecutionTrace


@dataclass
class AgentResult:
    output: str
    trace: ExecutionTrace


class Agent:
    def __init__(
        self,
        name: str,
        system_prompt: str,
        registry: ToolRegistry,
        llm: LLMClient,
        memory: SlidingWindowMemory = None,
        tracer: ExecutionTrace = None,
        max_iterations: int = 10,
    ):
        self.name = name
        self._registry = registry
        self._llm = llm
        self._tracer = tracer or ExecutionTrace()
        self._max_iterations = max_iterations

        if memory is None:
            self._memory = SlidingWindowMemory(system_prompt=system_prompt)
        else:
            memory._system_prompt = system_prompt
            self._memory = memory

    def run(self, goal: str) -> AgentResult:
        self._memory.add("user", goal)
        tools_schema = self._registry.to_openai_schema()
        consecutive_errors = 0

        for _ in range(self._max_iterations):
            message = self._llm.chat(self._memory.messages(), tools_schema)

            thought = message.content or ""
            tool_calls = message.tool_calls or []

            self._tracer.record("llm_decision", {
                "thought": thought,
                "tool_calls": [{"name": tc.function.name} for tc in tool_calls],
            })

            if not tool_calls:
                return AgentResult(output=thought, trace=self._tracer)

            # Serialize the assistant message so memory stays JSON-serializable
            assistant_msg = {"role": "assistant", "content": thought or None, "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ]}
            self._memory._messages.append(assistant_msg)

            for tc in tool_calls:
                tool_name = tc.function.name
                try:
                    arguments = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    arguments = {}

                self._tracer.record("tool_call", {"name": tool_name, "arguments": arguments})

                try:
                    result = self._registry.call(tool_name, arguments, tracer=self._tracer)
                    consecutive_errors = 0
                except Exception as e:
                    result = json.dumps({"error": str(e)})
                    consecutive_errors += 1
                    self._tracer.record("error", {
                        "tool": tool_name,
                        "message": str(e),
                        "consecutive": consecutive_errors,
                    })

                self._tracer.record("tool_result", {"name": tool_name, "result": result})
                self._memory._messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

                if consecutive_errors >= 3:
                    warning = f"Stopped: tool '{tool_name}' failed 3 consecutive times."
                    self._tracer.record("error", {"message": warning, "consecutive": consecutive_errors})
                    return AgentResult(output=warning, trace=self._tracer)

        warning = f"Stopped: reached max iterations ({self._max_iterations})."
        self._tracer.record("error", {"message": warning, "consecutive": 0})
        return AgentResult(output=warning, trace=self._tracer)

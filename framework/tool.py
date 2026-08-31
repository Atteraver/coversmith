import inspect
import json
from typing import Callable, get_type_hints


_PYTHON_TO_JSON_TYPE = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _build_schema(fn: Callable) -> dict:
    hints = get_type_hints(fn)
    sig = inspect.signature(fn)
    properties = {}
    required = []

    for name, param in sig.parameters.items():
        python_type = hints.get(name, str)
        json_type = _PYTHON_TO_JSON_TYPE.get(python_type, "string")
        properties[name] = {"type": json_type}
        if param.default is inspect.Parameter.empty:
            required.append(name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, dict] = {}

    def tool(self, description: str, require_human_approval: bool = False, approval_context_fn=None):
        """
        approval_context_fn: optional callable(arguments) -> str
          Called just before the y/n prompt to print a human-readable summary
          of what is about to happen. Use it to show domain context the raw
          arguments don't convey (e.g. the full rule details for apply_rule).
        """
        def decorator(fn: Callable):
            name = fn.__name__
            self._tools[name] = {
                "fn": fn,
                "description": description,
                "schema": _build_schema(fn),
                "require_human_approval": require_human_approval,
                "approval_context_fn": approval_context_fn,
            }
            return fn

        return decorator

    def to_openai_schema(self) -> list[dict]:
        result = []
        for name, meta in self._tools.items():
            result.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": meta["description"],
                    "parameters": meta["schema"],
                },
            })
        return result

    def get(self, name: str) -> dict | None:
        return self._tools.get(name)

    def call(self, name: str, arguments: dict, tracer=None) -> str:
        meta = self.get(name)
        if meta is None:
            raise ValueError(f"Unknown tool: {name}")

        if meta["require_human_approval"]:
            print(f"\n{'─'*55}")
            print(f"  APPROVAL REQUIRED")
            print(f"{'─'*55}")
            print(f"  The agent wants to call:  {name}")
            print(f"  Description: {meta['description']}")
            context_fn = meta.get("approval_context_fn")
            if context_fn:
                try:
                    context = context_fn(arguments)
                    if context:
                        print(f"\n{context}")
                except Exception:
                    pass
            else:
                print(f"  Arguments: {json.dumps(arguments, indent=2)}")
            print(f"{'─'*55}")
            answer = input("  Approve this action? [y/n]: ").strip().lower()
            approved = answer == "y"
            if tracer:
                tracer.record("approval", {
                    "tool": name,
                    "arguments": arguments,
                    "approved": approved,
                })
            if not approved:
                return json.dumps({"status": "rejected", "reason": "Human rejected the action."})

        result = meta["fn"](**arguments)
        if isinstance(result, (dict, list)):
            return json.dumps(result)
        return str(result)

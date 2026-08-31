import json
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class TraceEntry:
    step: int
    type: str
    timestamp: str
    data: dict


class ExecutionTrace:
    def __init__(self):
        self._entries: list[TraceEntry] = []
        self._step = 0

    def record(self, type: str, data: dict):
        self._step += 1
        self._entries.append(TraceEntry(
            step=self._step,
            type=type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            data=data,
        ))

    def print_summary(self):
        print(f"\n{'='*60}")
        print(f"  EXECUTION TRACE  ({len(self._entries)} entries)")
        print(f"{'='*60}")
        for e in self._entries:
            label = e.type.upper().replace("_", " ")
            print(f"\n[{e.step:02d}] {label}  ({e.timestamp[11:19]})")
            if e.type == "llm_decision":
                calls = e.data.get("tool_calls", [])
                if calls:
                    thought = e.data.get("thought", "")
                    if thought:
                        # Strip markdown so it prints cleanly in a terminal trace
                        import re
                        clean = re.sub(r"[*#`_~]", "", thought).strip()
                        clean = re.sub(r"\n+", " ", clean)
                        if len(clean) > 120:
                            clean = clean[:120].rsplit(" ", 1)[0] + " ..."
                        print(f"  Reasoning: {clean}")
                    print(f"  Calling: {', '.join(c['name'] for c in calls)}")
                else:
                    print("  → Returning final answer")
            elif e.type == "tool_call":
                print(f"  Tool:    {e.data['name']}")
                print(f"  Args:    {json.dumps(e.data['arguments'])[:120]}")
            elif e.type == "tool_result":
                result_str = str(e.data.get("result", ""))[:200]
                print(f"  Tool:    {e.data['name']}")
                print(f"  Result:  {result_str}")
            elif e.type == "approval":
                status = "APPROVED" if e.data["approved"] else "REJECTED"
                print(f"  Tool:    {e.data['tool']}  → {status}")
            elif e.type == "error":
                print(f"  Error:   {e.data.get('message', '')[:200]}")
                print(f"  Consecutive errors: {e.data.get('consecutive', 0)}")
        print(f"\n{'='*60}\n")

    def to_json(self) -> str:
        return json.dumps(
            [{"step": e.step, "type": e.type, "timestamp": e.timestamp, "data": e.data}
             for e in self._entries],
            indent=2,
        )

class SlidingWindowMemory:
    def __init__(self, system_prompt: str = "", max_messages: int = 20):
        self._system_prompt = system_prompt
        self._max = max_messages
        self._messages: list[dict] = []

    def add(self, role: str, content):
        self._messages.append({"role": role, "content": content})
        if len(self._messages) > self._max:
            self._messages = self._messages[-self._max:]

    def messages(self) -> list[dict]:
        result = []
        if self._system_prompt:
            result.append({"role": "system", "content": self._system_prompt})
        result.extend(self._messages)
        return result

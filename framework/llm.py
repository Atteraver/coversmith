import os
from openai import OpenAI


class LLMClient:
    def __init__(self, model: str = None, base_url: str = None, api_key: str = None):
        self._model = model or os.getenv("HAI_MODEL", "claude-sonnet-4-6")
        self._client = OpenAI(
            base_url=base_url or os.getenv("HAI_BASE_URL"),
            api_key=api_key or os.getenv("HAI_API_KEY"),
        )

    def chat(self, messages: list[dict], tools: list[dict] = None):
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools or None,
            tool_choice="auto" if tools else None,
        )
        return response.choices[0].message

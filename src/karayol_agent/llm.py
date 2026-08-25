from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class LLMUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OllamaClient:
    base_url: str = "http://localhost:11434"
    model: str = "llama3.2:3b"
    timeout_seconds: float = 60.0

    def chat_json(self, system_prompt: str, user_prompt: str) -> dict[str, object]:
        payload = json.dumps({
            "model": self.model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }).encode("utf-8")
        request = Request(
            self.base_url.rstrip("/") + "/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                response_data = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise LLMUnavailableError(f"Ollama isteği başarısız: {exc}") from exc
        try:
            content = response_data["message"]["content"]
            result = json.loads(content)
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise LLMUnavailableError("Ollama geçerli JSON yanıtı döndürmedi.") from exc
        if not isinstance(result, dict):
            raise LLMUnavailableError("Ollama yanıtı JSON nesnesi olmalı.")
        return result
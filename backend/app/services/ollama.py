import json
import time
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.schemas import ModelInfo


class OllamaError(RuntimeError):
    pass


SchemaT = TypeVar("SchemaT", bound=BaseModel)


class OllamaClient:
    def __init__(self, settings: Settings):
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.timeout = settings.job_timeout_seconds

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, timeout=self.timeout)

    def is_reachable(self) -> bool:
        try:
            with self._client() as client:
                return client.get("/api/tags", timeout=2).is_success
        except httpx.HTTPError:
            return False

    def list_models(self) -> list[ModelInfo]:
        try:
            with self._client() as client:
                response = client.get("/api/tags")
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ollama model listesi alınamadı: {exc}") from exc

        return [
            ModelInfo(
                name=model.get("name") or model.get("model"),
                size=model.get("size"),
                digest=model.get("digest"),
                modified_at=model.get("modified_at"),
            )
            for model in response.json().get("models", [])
            if model.get("name") or model.get("model")
        ]

    def chat_structured(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[SchemaT],
        *,
        temperature: float = 0.1,
        max_tokens: int = 1_200,
        request_timeout: float = 90,
    ) -> SchemaT:
        payload = {
            "model": model,
            "stream": False,
            "format": response_schema.model_json_schema(),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }

        last_error: Exception | None = None
        for attempt in range(2):
            try:
                with self._client() as client:
                    response = client.post("/api/chat", json=payload, timeout=request_timeout)
                    response.raise_for_status()
                content = response.json().get("message", {}).get("content", "")
                return response_schema.model_validate(json.loads(content))
            except (httpx.HTTPError, json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                if attempt == 0:
                    payload["messages"].append(
                        {
                            "role": "user",
                            "content": "Önceki yanıt geçerli JSON şemasına uymadı. Yalnızca şemaya uyan JSON döndür.",
                        }
                    )
                    time.sleep(0.2)
        raise OllamaError(f"Model geçerli yapılandırılmış yanıt üretemedi: {last_error}")

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            with self._client() as client:
                response = client.post("/api/embed", json={"model": model, "input": texts})
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OllamaError(f"Embedding üretilemedi: {exc}") from exc

        embeddings = response.json().get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise OllamaError("Ollama beklenen sayıda embedding döndürmedi.")
        if any(not isinstance(vector, list) or not vector for vector in embeddings):
            raise OllamaError("Ollama boş veya geçersiz embedding döndürdü.")
        return embeddings

    def validate_selection(self, chat_model: str, embedding_model: str) -> int:
        class Probe(BaseModel):
            durum: str

        self.chat_structured(
            chat_model,
            "Yalnızca istenen JSON şemasına uy.",
            "durum alanına hazır yaz.",
            Probe,
            temperature=0,
        )
        vector = self.embed(embedding_model, ["Türkçe belge erişim testi"])[0]
        return len(vector)

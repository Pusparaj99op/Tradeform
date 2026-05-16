"""
Ollama LLM client.
Connects to local Ollama instance for AI-powered market analysis.
"""

import ollama
from typing import Optional, List, Dict, Any, Generator
from tradeform.config import OllamaConfig


class OllamaClient:
    """Manages connection and communication with local Ollama models."""

    def __init__(self, config: OllamaConfig):
        self.config = config
        self._client = ollama.Client(host=config.host)
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        """
        Verify Ollama is running and the model is available.
        Returns True on success.
        """
        try:
            models = self._client.list()
            self._connected = True
            return True
        except Exception as e:
            self._connected = False
            raise ConnectionError(f"Cannot connect to Ollama at {self.config.host}: {e}")

    def list_models(self) -> List[str]:
        """List all available Ollama models."""
        try:
            response = self._client.list()
            models = response.get("models", [])
            return [m.get("name", m.get("model", "unknown")) for m in models]
        except Exception:
            return []

    def is_model_available(self, model: str = None) -> bool:
        """Check if the configured model is pulled and available."""
        model = model or self.config.model
        available = self.list_models()
        # Check both exact match and prefix match (e.g., "llama3.2" matches "llama3.2:latest")
        for m in available:
            if m == model or m.startswith(f"{model}:"):
                return True
        return False

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: str = None,
        temperature: float = None,
    ) -> str:
        """
        Send a chat completion request.
        Returns the full response text.
        """
        model = model or self.config.model
        temperature = temperature or self.config.temperature

        try:
            response = self._client.chat(
                model=model,
                messages=messages,
                options={"temperature": temperature},
            )
            return response["message"]["content"]
        except Exception as e:
            raise RuntimeError(f"Ollama chat failed: {e}")

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: str = None,
        temperature: float = None,
    ) -> Generator[str, None, None]:
        """
        Stream a chat completion response token by token.
        Yields text chunks as they arrive.
        """
        model = model or self.config.model
        temperature = temperature or self.config.temperature

        try:
            stream = self._client.chat(
                model=model,
                messages=messages,
                options={"temperature": temperature},
                stream=True,
            )
            for chunk in stream:
                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield content
        except Exception as e:
            yield f"\n[Error: {e}]"

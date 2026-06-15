import requests
import json
from typing import Dict, Any, Optional


class ExternalLLMClient:
    """
    This is the bridge between MCP and an external LLM (OpenAI / local / custom API).
    """

    def __init__(self, endpoint: str, api_key: Optional[str] = None):
        self.endpoint = endpoint
        self.api_key = api_key

    def _headers(self):
        headers = {
            "Content-Type": "application/json"
        }

        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        return headers

    def reason_about_repo(self, architecture: Dict[str, Any], question: str) -> str:
        """
        Sends repo structure + question to external LLM for reasoning.
        """

        payload = {
            "model": "external-reasoner",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are the reasoning engine for the Niblit system. "
                        "You analyze codebases, architecture, and execution flows. "
                        "You do NOT execute code. You ONLY reason."
                    )
                },
                {
                    "role": "user",
                    "content": json.dumps({
                        "question": question,
                        "architecture": architecture
                    }, indent=2)
                }
            ],
            "temperature": 0.3
        }

        try:
            res = requests.post(
                self.endpoint,
                headers=self._headers(),
                data=json.dumps(payload),
                timeout=60
            )

            data = res.json()

            # OpenAI-style compatibility
            return data["choices"][0]["message"]["content"]

        except Exception as e:
            return f"LLM ERROR: {str(e)}"
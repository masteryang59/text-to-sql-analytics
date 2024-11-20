"""A fake OpenAI chat-completions endpoint, served through httpx.MockTransport."""

from __future__ import annotations

import json
from collections import deque

import httpx
import openai


class FakeOpenAI:
    """Replies with queued message contents (or HTTP errors) and records every request."""

    def __init__(self):
        self.replies: deque = deque()
        self.requests: list[dict] = []

    def reply(self, content: str | dict, *, finish_reason: str = "stop") -> "FakeOpenAI":
        text = content if isinstance(content, str) else json.dumps(content)
        self.replies.append(("ok", text, finish_reason))
        return self

    def fail(self, status: int, message: str = "boom") -> "FakeOpenAI":
        self.replies.append(("error", status, message))
        return self

    def _handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        if not self.replies:
            return httpx.Response(500, json={"error": {"message": "no reply queued"}})
        kind, a, b = self.replies.popleft()
        if kind == "error":
            return httpx.Response(a, json={"error": {"message": b, "type": "server_error"}})
        return httpx.Response(200, json={
            "id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": body["model"],
            "choices": [{"index": 0, "finish_reason": b, "message": {"role": "assistant", "content": a}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })

    def client(self) -> openai.OpenAI:
        return openai.OpenAI(
            api_key="test", base_url="http://fake-openai/v1", max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(self._handle)),
        )


def answer(sql: str | None, explanation: str = "ok", chart: dict | None = None) -> dict:
    return {"sql": sql, "explanation": explanation,
            "chart": chart or {"type": "none", "x": None, "y": [], "series": None}}

def queue_message(data=None):
    if data is None:
        return None
    return data

def queue_message(data=None):
    if data is None:
        return None
    return data
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class OpenAICompatibleClient:
    def __init__(self, base_url: str, api_key: str, timeout_sec: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.timeout_sec = timeout_sec
        if not self.base_url:
            raise ValueError("api_base_url 不能为空")
        if not self.api_key:
            raise ValueError("api_key 不能为空")

    def embedding(self, model: str, text: str) -> list[float]:
        payload = {
            "model": model,
            "input": text,
        }
        data = self._post_json("/embeddings", payload)
        items = data.get("data", [])
        if not items:
            raise RuntimeError("Embedding 响应为空")
        vector = items[0].get("embedding")
        if not isinstance(vector, list):
            raise RuntimeError("Embedding 格式错误")
        return [float(v) for v in vector]

    def chat(self, model: str, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        data = self._post_json("/chat/completions", payload)
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("Chat 响应为空")
        message = choices[0].get("message", {})
        content = message.get("content", "")
        if not isinstance(content, str):
            raise RuntimeError("Chat 响应格式错误")
        return content.strip()

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url=url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise RuntimeError("API 返回非对象 JSON")
                return data
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="ignore")
            friendly = self._friendly_http_error(exc.code, details)
            raise RuntimeError(friendly) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"网络错误: {exc}") from exc

    @staticmethod
    def _friendly_http_error(status_code: int, details: str) -> str:
        lower = details.lower()
        quota_markers = (
            "insufficient_quota",
            "quota",
            "credit",
            "balance",
            "billing",
            "payment_required",
            "arrearage",
            "overdue-payment",
            "余额不足",
            "额度不足",
            "欠费",
        )
        if status_code == 400 and any(marker in lower for marker in ("arrearage", "overdue-payment", "欠费")):
            return (
                "API 调用失败：阿里云百炼账户欠费或已停用（Arrearage）。"
                "请先完成充值/续费，或切换到其他提供商后再重建索引。"
            )
        if status_code in (402, 429) and any(marker in lower for marker in quota_markers):
            return (
                "API 调用失败：额度不足或余额不足。请检查账户余额、套餐额度和账单状态，"
                "并确认当前模型在该平台已开通可用。"
            )
        if status_code == 401:
            return "API 调用失败：API Key 无效或已过期，请检查设置页中的 API Key。"
        if status_code == 403:
            return "API 调用失败：当前 Key 无权限访问该模型或接口，请检查模型权限。"
        if status_code == 429:
            return "API 调用失败：请求过于频繁或达到速率限制，请稍后重试。"
        return f"HTTP {status_code}: {details}"

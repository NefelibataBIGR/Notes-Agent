from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderPreset:
    id: str
    label: str
    api_base_url: str
    chat_model: str
    embedding_model: str
    api_key_url: str = ""
    docs_url: str = ""
    note: str = ""


PROVIDER_PRESETS: list[ProviderPreset] = [
    ProviderPreset(
        id="custom",
        label="自定义 (OpenAI 兼容)",
        api_base_url="https://api.openai.com/v1",
        chat_model="gpt-4o-mini",
        embedding_model="text-embedding-3-small",
        api_key_url="",
        docs_url="",
        note="可接任意 OpenAI 兼容网关，模型名按你的平台填写。",
    ),
    ProviderPreset(
        id="openai",
        label="OpenAI 官方",
        api_base_url="https://api.openai.com/v1",
        chat_model="gpt-4o-mini",
        embedding_model="text-embedding-3-small",
        api_key_url="https://platform.openai.com/api-keys",
        docs_url="https://platform.openai.com/docs/overview",
    ),
    ProviderPreset(
        id="deepseek",
        label="DeepSeek (国内可用)",
        api_base_url="https://api.deepseek.com/v1",
        chat_model="deepseek-chat",
        embedding_model="text-embedding-3-small",
        api_key_url="https://platform.deepseek.com/api_keys",
        docs_url="https://api-docs.deepseek.com/",
        note="DeepSeek 常用于对话，Embedding 可按你账户可用模型改写。",
    ),
    ProviderPreset(
        id="dashscope",
        label="阿里云百炼 DashScope",
        api_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        chat_model="qwen-plus",
        embedding_model="text-embedding-v3",
        api_key_url="https://www.alibabacloud.com/help/zh/model-studio/get-api-key",
        docs_url="https://help.aliyun.com/zh/model-studio/",
    ),
    ProviderPreset(
        id="zhipu",
        label="智谱 GLM (OpenAPI)",
        api_base_url="https://open.bigmodel.cn/api/paas/v4",
        chat_model="glm-4-flash",
        embedding_model="embedding-3",
        api_key_url="https://docs.bigmodel.cn/cn/guide/start/quick-start",
        docs_url="https://docs.bigmodel.cn/cn/api/introduction",
    ),
    ProviderPreset(
        id="siliconflow",
        label="硅基流动 SiliconFlow",
        api_base_url="https://api.siliconflow.cn/v1",
        chat_model="Qwen/Qwen2.5-72B-Instruct",
        embedding_model="BAAI/bge-m3",
        api_key_url="https://docs.siliconflow.com/quickstart",
        docs_url="https://docs.siliconflow.com/en/api-reference/introduction",
    ),
    ProviderPreset(
        id="volcark",
        label="火山方舟 Ark (OpenAI 兼容)",
        api_base_url="https://ark.cn-beijing.volces.com/api/v3",
        chat_model="your-chat-endpoint-id",
        embedding_model="your-embedding-endpoint-id",
        api_key_url="https://doubao.apifox.cn/",
        docs_url="https://www.volcengine.com/docs/82379",
        note="方舟通常使用 Endpoint ID 作为模型名。",
    ),
]


def get_provider_by_id(provider_id: str) -> ProviderPreset:
    for provider in PROVIDER_PRESETS:
        if provider.id == provider_id:
            return provider
    return PROVIDER_PRESETS[0]

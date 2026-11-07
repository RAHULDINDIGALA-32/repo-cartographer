from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderProfile:
    name: str
    kind: str
    base_url: str
    key_setting: str
    default_headers: dict[str, str] | None = None


PROFILES = {
    "anthropic": ProviderProfile(
        "anthropic", "anthropic", "https://api.anthropic.com", "anthropic_api_key"
    ),
    "groq": ProviderProfile(
        "groq", "openai_compatible", "https://api.groq.com/openai/v1", "groq_api_key"
    ),
    "openrouter": ProviderProfile(
        "openrouter", "openai_compatible", "https://openrouter.ai/api/v1", "openrouter_api_key"
    ),
    "custom": ProviderProfile(
        "custom", "openai_compatible", "http://localhost:8000/v1", "custom_api_key"
    ),
}


def get_profile(name: str) -> ProviderProfile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        raise ValueError(
            f"Unknown LLM provider '{name}'; choose one of {', '.join(PROFILES)}"
        ) from exc

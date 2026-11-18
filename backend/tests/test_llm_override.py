"""LLM_* ใช้แทน TYPHOON_* เฉพาะงานแปล ส่วนอื่น (OCR สลิป) ยังใช้ TYPHOON_*"""
import types

import pytest

from app.pipeline import translate as T


@pytest.fixture(autouse=True)
def _restore_settings():
    keys = ("typhoon_api_key", "typhoon_base_url", "typhoon_model", "llm_api_key", "llm_base_url",
            "llm_model", "typhoon_reasoning_effort")
    old = {k: getattr(T.settings, k) for k in keys}
    yield
    for k, v in old.items():
        object.__setattr__(T.settings, k, v)
    T._client = None


def _run(monkeypatch, **cfg):
    seen = {}

    class FakeClient:
        def __init__(self, api_key, base_url):
            seen.update(api_key=api_key, base_url=base_url)
            self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))

        def _create(self, **kw):
            seen["model"] = kw["model"]
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="x"))])

    import openai
    monkeypatch.setattr(openai, "OpenAI", FakeClient)
    monkeypatch.setattr(T, "_client", None)
    base = dict(typhoon_api_key="tk", typhoon_base_url="https://ty/v1", typhoon_model="ty-model",
                llm_api_key="", llm_base_url="", llm_model="", typhoon_reasoning_effort="")
    base.update(cfg)
    for k, v in base.items():
        object.__setattr__(T.settings, k, v)
    T._chat("s", "u")
    return seen


def test_default_uses_typhoon(monkeypatch):
    s = _run(monkeypatch)
    assert (s["api_key"], s["base_url"], s["model"]) == ("tk", "https://ty/v1", "ty-model")


def test_llm_overrides_typhoon(monkeypatch):
    s = _run(monkeypatch, llm_api_key="lk", llm_base_url="https://llm/v1", llm_model="qwen")
    assert (s["api_key"], s["base_url"], s["model"]) == ("lk", "https://llm/v1", "qwen")

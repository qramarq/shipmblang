from shipmblang.providers import OpenAICompatibleProvider, load_chat_provider
from shipmblang.runtime_context import build_runtime_context, build_system_prompt


def test_shipmb_context_is_runtime_owned():
    context = build_runtime_context(task="report available capabilities")
    prompt = build_system_prompt(task="report available capabilities")

    assert context["identity"].startswith("ShipMB")
    assert context["device_families"]
    assert "You are ShipMB." in prompt
    assert "Available device families and resources:" in prompt
    assert "runtime context, not from model training" in prompt


def test_no_model_provider_is_selected_by_default(monkeypatch):
    monkeypatch.delenv("SHIPMB_MODEL_PROVIDER", raising=False)
    assert load_chat_provider() is None


def test_openai_compatible_provider_is_not_model_specific(monkeypatch):
    monkeypatch.setenv("SHIPMB_MODEL_PROVIDER", "openai_compatible")
    monkeypatch.setenv("SHIPMB_MODEL_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("SHIPMB_MODEL_NAME", "any-instruct-model")
    provider = load_chat_provider()

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.model == "any-instruct-model"


def test_shiplm_is_opt_in_and_needs_explicit_checkpoint(monkeypatch):
    monkeypatch.delenv("SHIPMB_MODEL_CHECKPOINT", raising=False)
    monkeypatch.delenv("SHIPMB_MODEL_TOKENIZER", raising=False)
    for name in ("shiplm", "drip"):
        monkeypatch.setenv("SHIPMB_MODEL_PROVIDER", name)
        assert load_chat_provider() is None


def test_unknown_provider_is_unsupported(monkeypatch):
    monkeypatch.setenv("SHIPMB_MODEL_PROVIDER", "nonsense")
    try:
        load_chat_provider()
    except ValueError as exc:
        assert "unsupported ShipMB model provider" in str(exc)
    else:
        raise AssertionError("unknown providers must be rejected")

"""Cloudflare Workers AI 백엔드와 재시도·회로 차단 회귀 테스트.

실제 네트워크는 쓰지 않는다. 가짜 세션을 주입해 요청 구성, 오류 분류,
회로 차단을 검증한다.
"""

import json
import logging
from datetime import datetime, timezone

import pytest
import requests

from llm.backends import (
    CloudflareWorkersAIBackend,
    LLMBackendError,
    ResilientBackend,
)
from llm.translator import TranslationError, TranslationService

API_TOKEN = "cf-secret-token-should-never-be-logged"
GENERATE_KWARGS = {
    "system_prompt": "system",
    "user_prompt": "user",
    "max_tokens": 512,
    "temperature": 0.1,
}


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload


class _FakeSession:
    """미리 준비한 응답(또는 예외)을 순서대로 돌려주는 requests.Session 대역."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        item = self._responses.pop(0) if self._responses else _FakeResponse()
        if isinstance(item, Exception):
            raise item
        return item


def _chat_completion(content, usage=None):
    payload = {"choices": [{"message": {"role": "assistant", "content": content}}]}
    if usage is not None:
        payload["usage"] = usage
    return _FakeResponse(payload=payload)


def _cloudflare(session, **overrides):
    kwargs = {
        "account_id": "acct-1",
        "api_token": API_TOKEN,
        "model": "@cf/qwen/qwen3-30b-a3b-fp8",
        "base_url": "https://api.cloudflare.com/client/v4",
        "timeout": 45,
        "session": session,
    }
    kwargs.update(overrides)
    return CloudflareWorkersAIBackend(**kwargs)


# ── 요청 구성 ─────────────────────────────────────────


def test_request_uses_openai_compatible_endpoint():
    session = _FakeSession(_chat_completion('{"title": "제목"}'))

    content = _cloudflare(session).generate(**GENERATE_KWARGS)

    assert content == '{"title": "제목"}'
    call = session.calls[0]
    assert call["url"] == (
        "https://api.cloudflare.com/client/v4/accounts/acct-1/ai/v1/chat/completions"
    )
    assert call["headers"]["Authorization"] == f"Bearer {API_TOKEN}"
    assert call["headers"]["Content-Type"] == "application/json"
    assert call["timeout"] == 45
    payload = call["json"]
    assert payload["model"] == "@cf/qwen/qwen3-30b-a3b-fp8"
    assert payload["stream"] is False
    assert payload["temperature"] == 0.1
    assert payload["max_tokens"] == 512
    # Qwen3 기본 모델이라 시스템 프롬프트에 /no_think가 덧붙는다.
    assert payload["messages"] == [
        {"role": "system", "content": "system\n/no_think"},
        {"role": "user", "content": "user"},
    ]


def test_per_request_timeout_overrides_default():
    session = _FakeSession(_chat_completion("{}"))

    _cloudflare(session).generate(**GENERATE_KWARGS, timeout=600)

    assert session.calls[0]["timeout"] == 600


def test_suppresses_qwen3_thinking():
    """Qwen3는 thinking이 max_tokens를 다 먹고 content를 비운다. /no_think로 막는다."""
    session = _FakeSession(_chat_completion("{}"))

    _cloudflare(session, model="@cf/qwen/qwen3-30b-a3b-fp8").generate(**GENERATE_KWARGS)

    assert session.calls[0]["json"]["messages"][0]["content"] == "system\n/no_think"
    assert session.calls[0]["json"]["messages"][1]["content"] == "user"


def test_leaves_non_qwen3_prompts_untouched():
    session = _FakeSession(_chat_completion("{}"))

    _cloudflare(session, model="@cf/meta/llama-3.1-8b-instruct").generate(
        **GENERATE_KWARGS
    )

    assert session.calls[0]["json"]["messages"][0]["content"] == "system"


def test_requires_credentials():
    with pytest.raises(ValueError):
        CloudflareWorkersAIBackend(account_id="", api_token="", model="m")


# ── 사용량 로깅 ───────────────────────────────────────


def test_logs_usage_with_neurons(caplog):
    session = _FakeSession(
        _chat_completion(
            "{}",
            usage={
                "prompt_tokens": 710,
                "completion_tokens": 196,
                "neurons": 9.2755,
            },
        )
    )
    with caplog.at_level(logging.INFO, logger="llm.backends"):
        _cloudflare(session).generate(**GENERATE_KWARGS)

    assert "input_tokens=710" in caplog.text
    assert "output_tokens=196" in caplog.text
    # 과금 단위는 추정하지 않고 응답이 준 값을 그대로 남긴다.
    assert "neurons=9.28" in caplog.text


def test_logs_unknown_usage_when_absent(caplog):
    session = _FakeSession(_chat_completion("{}"))
    with caplog.at_level(logging.INFO, logger="llm.backends"):
        _cloudflare(session).generate(**GENERATE_KWARGS)

    assert "usage=unknown" in caplog.text


# ── 응답 검증 ─────────────────────────────────────────


@pytest.mark.parametrize(
    "response",
    [
        _FakeResponse(payload={"choices": []}),
        _FakeResponse(payload={"choices": [{"message": {"content": "  "}}]}),
        _FakeResponse(payload={"result": "unexpected"}),
        _FakeResponse(payload=None, text="<html>gateway</html>"),
    ],
    ids=["empty-choices", "blank-content", "no-choices", "not-json"],
)
def test_rejects_unusable_responses(response):
    with pytest.raises(LLMBackendError) as excinfo:
        _cloudflare(_FakeSession(response)).generate(**GENERATE_KWARGS)

    error = excinfo.value
    assert error.provider == "cloudflare"
    assert error.reason == "invalid_response"
    assert error.retryable is True


def test_reports_reasoning_only_response():
    """thinking에만 답을 쓰고 끝난 응답은 원인이 로그에서 보여야 한다."""
    session = _FakeSession(
        _FakeResponse(
            payload={
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": "", "reasoning_content": "x" * 3510},
                    }
                ]
            }
        )
    )

    with pytest.raises(LLMBackendError) as excinfo:
        _cloudflare(session).generate(**GENERATE_KWARGS)

    detail = excinfo.value.detail
    assert "finish_reason=length" in detail
    assert "reasoning_chars=3510" in detail


def test_accepts_v4_envelope_wrapped_choices():
    session = _FakeSession(
        _FakeResponse(
            payload={
                "success": True,
                "result": {
                    "choices": [{"message": {"content": "wrapped"}}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 7},
                },
            }
        )
    )

    assert _cloudflare(session).generate(**GENERATE_KWARGS) == "wrapped"


# ── 오류 분류 ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("status", "reason", "retryable", "fatal"),
    [
        (429, "rate_limited", True, False),
        (500, "server_error", True, False),
        (503, "server_error", True, False),
        (401, "auth_error", False, True),
        (403, "auth_error", False, True),
        (400, "bad_request", False, True),
        (422, "bad_request", False, True),
    ],
)
def test_classifies_http_status(status, reason, retryable, fatal):
    session = _FakeSession(
        _FakeResponse(
            status_code=status,
            payload={"errors": [{"code": 7003, "message": "request failed"}]},
        )
    )

    with pytest.raises(LLMBackendError) as excinfo:
        _cloudflare(session).generate(**GENERATE_KWARGS)

    error = excinfo.value
    assert (error.reason, error.retryable, error.fatal) == (reason, retryable, fatal)
    assert error.status_code == status
    assert error.quota_exhausted is False


@pytest.mark.parametrize(
    "error",
    [requests.Timeout("read timed out"), requests.ConnectionError("refused")],
    ids=["timeout", "connection"],
)
def test_transport_errors_are_retryable(error):
    with pytest.raises(LLMBackendError) as excinfo:
        _cloudflare(_FakeSession(error)).generate(**GENERATE_KWARGS)

    assert excinfo.value.retryable is True
    assert excinfo.value.quota_exhausted is False


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (429, "You have exceeded your daily free tier limit of 10000 Neurons"),
        (402, "Payment required"),
    ],
    ids=["neuron-quota", "payment-required"],
)
def test_detects_quota_exhaustion(status, message):
    session = _FakeSession(
        _FakeResponse(status_code=status, payload={"error": {"message": message}})
    )

    with pytest.raises(LLMBackendError) as excinfo:
        _cloudflare(session).generate(**GENERATE_KWARGS)

    assert excinfo.value.quota_exhausted is True
    assert excinfo.value.retryable is False


def test_never_leaks_api_token(caplog):
    session = _FakeSession(
        _FakeResponse(
            status_code=403,
            payload={
                "errors": [
                    {
                        "code": 10000,
                        "message": f"Invalid token {API_TOKEN} for this account",
                    }
                ]
            },
        )
    )
    with caplog.at_level(logging.DEBUG, logger="llm.backends"):
        with pytest.raises(LLMBackendError) as excinfo:
            _cloudflare(session).generate(**GENERATE_KWARGS)

    assert API_TOKEN not in str(excinfo.value)
    assert API_TOKEN not in caplog.text
    assert "***" in str(excinfo.value)


# ── 재시도와 회로 차단 ────────────────────────────────


class _Clock:
    def __init__(self, start=0.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def _resilient(session, clock=None, **overrides):
    clock = clock or _Clock()
    kwargs = {
        "backend": _cloudflare(session),
        "max_attempts": 2,
        "failure_threshold": 3,
        "cooldown_seconds": 300,
        "clock": clock,
        "sleep": lambda _seconds: None,
    }
    kwargs.update(overrides)
    return ResilientBackend(**kwargs), clock


def test_passes_through_on_success():
    session = _FakeSession(_chat_completion("ok"))
    backend, _ = _resilient(session)

    assert backend.generate(**GENERATE_KWARGS) == "ok"
    assert len(session.calls) == 1
    assert backend.circuit_status() == "closed"


def test_retries_retryable_errors_then_succeeds():
    session = _FakeSession(
        _FakeResponse(status_code=503, payload={"errors": [{"message": "down"}]}),
        _chat_completion("recovered"),
    )
    backend, _ = _resilient(session)

    assert backend.generate(**GENERATE_KWARGS) == "recovered"
    assert len(session.calls) == 2


def test_honours_retry_after_within_cap():
    slept = []
    session = _FakeSession(
        _FakeResponse(
            status_code=429,
            payload={"error": {"message": "slow down"}},
            headers={"Retry-After": "2"},
        ),
        _chat_completion("after-retry"),
    )
    backend, _ = _resilient(session, sleep=slept.append)

    assert backend.generate(**GENERATE_KWARGS) == "after-retry"
    assert slept == [2.0]


def test_does_not_retry_non_retryable_errors():
    session = _FakeSession(
        _FakeResponse(status_code=400, payload={"error": {"message": "bad json"}}),
    )
    backend, _ = _resilient(session)

    with pytest.raises(LLMBackendError):
        backend.generate(**GENERATE_KWARGS)
    assert len(session.calls) == 1


def test_quota_exhaustion_opens_circuit_until_next_utc_midnight():
    noon = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc).timestamp()
    session = _FakeSession(
        _FakeResponse(
            status_code=429,
            payload={"error": {"message": "Daily free tier Neurons exhausted"}},
        )
    )
    backend, clock = _resilient(session, clock=_Clock(noon))

    with pytest.raises(LLMBackendError):
        backend.generate(**GENERATE_KWARGS)
    # 할당량 소진은 재시도하지 않는다.
    assert len(session.calls) == 1

    expected = datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc)
    assert "2026-08-02T00:00:00Z" in backend.circuit_status()
    assert "quota_exhausted" in backend.circuit_status()

    # 회로가 열린 동안에는 네트워크를 아예 건드리지 않고 즉시 실패한다.
    clock.advance(3600)
    with pytest.raises(LLMBackendError) as excinfo:
        backend.generate(**GENERATE_KWARGS)
    assert len(session.calls) == 1
    assert excinfo.value.reason == "circuit_open"

    # UTC 자정을 넘기면 다시 시도한다.
    clock.now = expected.timestamp() + 1
    assert backend.circuit_status() == "closed"


def test_auth_error_opens_circuit_until_restart():
    session = _FakeSession(
        _FakeResponse(status_code=401, payload={"error": {"message": "bad token"}})
    )
    backend, clock = _resilient(session)

    with pytest.raises(LLMBackendError):
        backend.generate(**GENERATE_KWARGS)
    assert "permanent" in backend.circuit_status()

    clock.advance(10 * 24 * 3600)
    with pytest.raises(LLMBackendError):
        backend.generate(**GENERATE_KWARGS)
    assert len(session.calls) == 1


def test_consecutive_failures_open_circuit_and_cooldown_expires():
    session = _FakeSession(
        *[requests.ConnectionError("x")] * 4,
        _chat_completion("back-online"),
    )
    backend, clock = _resilient(session, failure_threshold=3, max_attempts=2)

    # 호출 1회당 재시도 2회이므로 두 번째 호출에서 임계치 3에 도달한다.
    with pytest.raises(LLMBackendError):
        backend.generate(**GENERATE_KWARGS)
    assert backend.circuit_status() == "closed"
    with pytest.raises(LLMBackendError):
        backend.generate(**GENERATE_KWARGS)
    assert backend.circuit_status().startswith("open(")
    assert len(session.calls) == 4

    # 쿨다운 중에는 건너뛴다.
    with pytest.raises(LLMBackendError):
        backend.generate(**GENERATE_KWARGS)
    assert len(session.calls) == 4

    clock.advance(301)
    assert backend.generate(**GENERATE_KWARGS) == "back-online"
    assert len(session.calls) == 5
    assert backend.circuit_status() == "closed"


# ── TranslationService 통합 ───────────────────────────


def _service(backend):
    service = object.__new__(TranslationService)
    service._backend = backend
    service._enabled = True
    service._num_predict = 512
    service._temperature = 0.1
    service._brief_content_limit = 180
    service._prompts = {"global": "prompt"}
    return service


def test_service_translates_through_the_backend():
    payload = json.dumps(
        {
            "title": "제목",
            "content": "본문 요약입니다.",
            "mentioned_stocks": ["600519"],
            "sentiment": 0.4,
            "impact": "medium",
        },
        ensure_ascii=False,
    )
    session = _FakeSession(_chat_completion(payload))
    backend, _ = _resilient(session)

    result = _service(backend).translate_article("global", "原文", "原文 본문")

    assert result.title == "제목"
    assert result.mentioned_stocks == ["600519"]
    assert result.sentiment == 0.4
    system_prompt = session.calls[0]["json"]["messages"][0]["content"]
    assert system_prompt.startswith("prompt")
    assert "JSON output hard rules" in system_prompt


def test_service_raises_translation_error_when_backend_fails():
    session = _FakeSession(requests.Timeout("t"), requests.Timeout("t"))
    backend, _ = _resilient(session)

    with pytest.raises(TranslationError, match="timeout"):
        _service(backend).translate_article("global", "原文", "原文 본문")

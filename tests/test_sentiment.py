import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test-chat")

from llm.translator import TranslationError, TranslationService
from news.utils import format_sentiment_line, normalize_stock_code


def _parse(payload: dict):
    service = object.__new__(TranslationService)
    return service._parse_translation(json.dumps(payload, ensure_ascii=False))


def test_parse_translation_reads_sentiment_and_impact():
    result = _parse(
        {
            "title": "제목",
            "content": "본문",
            "mentioned_stocks": ["600519"],
            "sentiment": 0.6,
            "impact": "HIGH",
        }
    )
    assert result.sentiment == 0.6
    assert result.impact == "high"


def test_parse_translation_tolerates_missing_or_invalid_sentiment():
    result = _parse({"title": "제목", "content": "본문", "mentioned_stocks": []})
    assert result.sentiment is None
    assert result.impact == ""

    result = _parse(
        {
            "title": "제목",
            "content": "본문",
            "mentioned_stocks": [],
            "sentiment": "매우긍정",
            "impact": "엄청남",
        }
    )
    assert result.sentiment is None
    assert result.impact == ""


def test_sentiment_clamped_to_range():
    result = _parse(
        {"title": "제목", "content": "본문", "mentioned_stocks": [], "sentiment": -3}
    )
    assert result.sentiment == -1.0


def test_format_sentiment_line_markers():
    assert "긍정" in format_sentiment_line(0.5)
    assert "부정" in format_sentiment_line(-0.5, "high")
    assert "높음" in format_sentiment_line(-0.5, "high")
    assert "중립" in format_sentiment_line(0.0)
    assert format_sentiment_line(None) == ""


def test_normalize_stock_code():
    assert normalize_stock_code("700") == "00700"
    assert normalize_stock_code("600519") == "600519"
    assert normalize_stock_code("SZ000665") == "000665"
    assert normalize_stock_code("") == ""


def test_translation_rewrites_overlong_brief_instead_of_cutting():
    service = object.__new__(TranslationService)
    service._enabled = True
    service._brief_content_limit = 150
    service._prompts = {"global": "prompt"}
    responses = iter(
        [
            json.dumps(
                {
                    "title": "제목",
                    "content": "가" * 170,
                    "mentioned_stocks": [],
                    "sentiment": 0.2,
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "title": "제목",
                    "content": "핵심 내용을 완결된 단신으로 요약했다.",
                    "mentioned_stocks": [],
                    "sentiment": 0.2,
                },
                ensure_ascii=False,
            ),
        ]
    )
    calls = []

    def request(*args, **kwargs):
        calls.append(kwargs)
        return next(responses)

    service._request_translation = request

    result = service.translate_article("global", "원문 제목", "원문 전체")

    assert result.content == "핵심 내용을 완결된 단신으로 요약했다."
    assert len(calls) == 2
    assert calls[1]["retry_for_length"] is True


def test_translation_preserves_complete_rewrite_if_limit_still_missed():
    service = object.__new__(TranslationService)
    service._enabled = True
    service._brief_content_limit = 150
    service._prompts = {"global": "prompt"}
    complete_long_brief = "완결된 장문을 기계적으로 자르지 않고 보존한다. " * 6
    response = json.dumps(
        {
            "title": "제목",
            "content": complete_long_brief,
            "mentioned_stocks": [],
            "sentiment": -0.2,
        },
        ensure_ascii=False,
    )
    service._request_translation = lambda *args, **kwargs: response

    result = service.translate_article("global", "원문 제목", "원문 전체")

    assert len(complete_long_brief) > 150
    assert result.content == complete_long_brief.strip()
    assert not result.content.endswith("...")


def test_translation_accepts_small_overage_without_rewrite():
    service = object.__new__(TranslationService)
    service._enabled = True
    service._brief_content_limit = 150
    service._prompts = {"global": "prompt"}
    response = json.dumps(
        {
            "title": "제목",
            "content": "가" * 161,
            "mentioned_stocks": [],
            "sentiment": 0.1,
        },
        ensure_ascii=False,
    )
    calls = []

    def request(*args, **kwargs):
        calls.append(kwargs)
        return response

    service._request_translation = request

    result = service.translate_article("global", "원문 제목", "원문 전체")

    assert len(result.content) == 161
    assert len(calls) == 1


def test_translation_rewrites_chinese_title_in_korean():
    service = object.__new__(TranslationService)
    service._enabled = True
    service._brief_content_limit = 180
    service._prompts = {"global": "prompt"}
    responses = iter(
        [
            json.dumps(
                {
                    "title": "沪指跌破3800点，光纤板块多只个股跌停",
                    "content": "상하이종합지수가 하락했다.",
                    "mentioned_stocks": [],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "title": "상하이종합지수 3,800선 하회, 광섬유주 다수 하한가",
                    "content": "상하이종합지수가 하락했다.",
                    "mentioned_stocks": [],
                },
                ensure_ascii=False,
            ),
        ]
    )
    calls = []

    def request(*args, **kwargs):
        calls.append(kwargs)
        return next(responses)

    service._request_translation = request

    result = service.translate_article("global", "원문 제목", "원문 전체")

    assert result.title.startswith("상하이종합지수")
    assert len(calls) == 2
    assert calls[1]["retry_for_translation"] is True


def test_translation_uses_korean_brief_when_title_stays_chinese():
    service = object.__new__(TranslationService)
    service._enabled = True
    service._brief_content_limit = 180
    service._prompts = {"global": "prompt"}
    response = json.dumps(
        {
            "title": "傲意科技首发具身智能教育产品矩阵",
            "content": "오의과기가 체화지능 교육제품군을 처음 공개했다.",
            "mentioned_stocks": [],
            "sentiment": 0.3,
            "impact": "medium",
        },
        ensure_ascii=False,
    )
    calls = []

    def request(*args, **kwargs):
        calls.append(kwargs)
        return response

    service._request_translation = request

    result = service.translate_article("global", "중국어 원문", "중국어 본문")

    assert result.title == "오의과기가 체화지능 교육제품군을 처음 공개했다"
    assert result.content == "오의과기가 체화지능 교육제품군을 처음 공개했다."
    assert result.sentiment == 0.3
    assert len(calls) == 2


def test_translation_still_rejects_chinese_title_and_content():
    service = object.__new__(TranslationService)
    service._enabled = True
    service._brief_content_limit = 180
    service._prompts = {"global": "prompt"}
    response = json.dumps(
        {
            "title": "傲意科技首发具身智能教育产品矩阵",
            "content": "傲意科技发布智能教育产品矩阵",
            "mentioned_stocks": [],
        },
        ensure_ascii=False,
    )
    service._request_translation = lambda *args, **kwargs: response

    with pytest.raises(
        TranslationError,
        match="title remains untranslated Chinese",
    ):
        service.translate_article("global", "중국어 원문", "중국어 본문")


def test_translation_uses_first_valid_result_when_rewrite_is_invalid():
    service = object.__new__(TranslationService)
    service._enabled = True
    service._brief_content_limit = 150
    service._prompts = {"global": "prompt"}
    first_content = "가" * 170
    responses = iter(
        [
            json.dumps(
                {
                    "title": "제목",
                    "content": first_content,
                    "mentioned_stocks": [],
                    "sentiment": -0.4,
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "title": "제목",
                    "mentioned_stocks": [],
                    "sentiment": -0.4,
                },
                ensure_ascii=False,
            ),
        ]
    )
    service._request_translation = lambda *args, **kwargs: next(responses)

    result = service.translate_article("global", "원문 제목", "원문 전체")

    assert result.content == first_content
    assert result.sentiment == -0.4

from fastapi.testclient import TestClient

import webpub
import webpub_export


def test_publish_market_and_serve_it(tmp_path, monkeypatch):
    monkeypatch.setattr(webpub_export, "WEBPUB_DIR", tmp_path)
    monkeypatch.setattr(webpub_export, "MARKET_JSON", tmp_path / "market.json")
    monkeypatch.setattr(webpub_export, "MARKET_CHART", tmp_path / "market_chart.png")
    monkeypatch.setattr(webpub_export, "META_JSON", tmp_path / "meta.json")
    monkeypatch.setattr(webpub, "WEBPUB_DIR", tmp_path)

    webpub_export.publish_market(
        b"png-bytes",
        {"KR": {"avg_sentiment": 0.2, "count": 12, "daily": []}},
        None,
        7,
    )

    client = TestClient(webpub.build_app())
    payload = client.get("/api/market").json()
    assert payload["markets"]["KR"]["count"] == 12
    assert client.get("/market_chart.png").content == b"png-bytes"
    assert client.get("/").status_code == 200


def test_publish_research_preserves_full_result_and_history(tmp_path, monkeypatch):
    monkeypatch.setattr(webpub_export, "WEBPUB_DIR", tmp_path)
    monkeypatch.setattr(webpub_export, "RESEARCH_JSON", tmp_path / "research.json")
    monkeypatch.setattr(webpub_export, "META_JSON", tmp_path / "meta.json")
    monkeypatch.setattr(webpub, "WEBPUB_DIR", tmp_path)

    result = {"summary": "시장 요약", "risks": ["변동성"]}
    webpub_export.publish_research("반도체", result, [{"summary": "이전 결과"}])

    payload = TestClient(webpub.build_app()).get("/api/research").json()
    assert payload["sight"] == "반도체"
    assert payload["last_result"] == result
    assert payload["history"] == [{"summary": "이전 결과"}]


def test_public_pages_share_one_shell(tmp_path, monkeypatch):
    """세 화면이 같은 헤더·푸터를 쓰고 현재 위치를 표시한다."""
    monkeypatch.setattr(webpub, "WEBPUB_DIR", tmp_path)
    client = TestClient(webpub.build_app())

    for path in ("/", "/research", "/about"):
        page = client.get(path)
        assert page.status_code == 200
        body = page.text
        # 산출물이 없어도 화면 자체는 그려진다. 값은 브라우저가 /api/*로 채운다.
        assert "nunchi" in body
        for link in ("/", "/research", "/about"):
            assert "href='" + link + "'" in body
        assert "href='" + path + "' aria-current='page'" in body


def test_pages_are_built_once_and_do_not_touch_the_filesystem(tmp_path, monkeypatch):
    """페이지는 정적 문자열이다. 요청마다 다시 조립하거나 산출물을 읽지 않는다."""
    monkeypatch.setattr(webpub, "WEBPUB_DIR", tmp_path / "missing")
    client = TestClient(webpub.build_app())

    first = client.get("/about").text
    assert first == client.get("/about").text
    assert first == webpub.ABOUT_HTML


def test_research_metadata_uses_the_same_section_card_pattern():
    """연구 결과 메타데이터도 요약·리스크와 같은 섹션형 카드로 표시한다."""
    body = webpub.RESEARCH_HTML

    assert "</span>연구 결과</div>" in body
    assert "<dl class='brief research-meta'>" in body
    assert "<div class='statstrip'>" not in body

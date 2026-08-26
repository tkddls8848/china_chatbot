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

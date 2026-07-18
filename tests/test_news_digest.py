from news.utils import chunk_message_items, truncate_text


def test_truncate_text_remains_available_for_titles():
    result = truncate_text("가" * 150, 100)

    assert len(result) == 100
    assert result.endswith("...")


def test_truncate_text_keeps_short_text():
    assert truncate_text("짧은 기사 요약", 100) == "짧은 기사 요약"


def test_chunk_message_items_keeps_articles_whole_and_ordered():
    items = ["가" * 40, "나" * 40, "다" * 40]

    chunks = chunk_message_items(
        items,
        text_getter=lambda item: item,
        max_body_length=81,
        separator="\n",
    )

    assert chunks == [[items[0], items[1]], [items[2]]]
    assert [item for chunk in chunks for item in chunk] == items

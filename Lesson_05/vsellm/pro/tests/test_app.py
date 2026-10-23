from app import health, home


def test_health_describes_hybrid_search() -> None:
    payload = health()
    assert payload["documents"] == 1
    assert payload["chunks_before_indexing"] >= 100
    assert payload["search"] == "vector + BM25 + RRF"


def test_home_page_is_available() -> None:
    assert str(home().path).endswith("static/index.html")


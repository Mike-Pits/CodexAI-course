from app import health, home


def test_health_reports_five_documents() -> None:
    payload = health()
    assert payload["documents"] == 5
    assert payload["chunks_before_indexing"] > 5


def test_home_page_is_available() -> None:
    response = home()
    assert str(response.path).endswith("static/index.html")


from __future__ import annotations

import base64
from pathlib import Path

import pytest
from pydantic import ValidationError

from confluence_mcp.config import Settings
from tests.conftest import BASE, make_settings


def test_url_trailing_slash_and_quotes_stripped() -> None:
    s = make_settings(confluence_url='"https://c.example.com/confluence/"')
    assert s.confluence_url == "https://c.example.com/confluence"


def test_url_must_have_scheme() -> None:
    with pytest.raises(ValidationError, match="must start with http"):
        make_settings(confluence_url="c.example.com")


def test_token_auth_header() -> None:
    assert make_settings().get_auth_headers() == {"Authorization": "Bearer secret-token"}


def test_token_preferred_over_basic() -> None:
    s = make_settings(confluence_username="u", confluence_password="p")
    assert s.get_auth_headers()["Authorization"].startswith("Bearer ")


def test_basic_auth_header() -> None:
    s = Settings(confluence_url=BASE, confluence_username="alice", confluence_password="pw")
    expected = base64.b64encode(b"alice:pw").decode()
    assert s.get_auth_headers() == {"Authorization": f"Basic {expected}"}


def test_missing_auth_fails() -> None:
    with pytest.raises(ValidationError, match="CONFLUENCE_TOKEN"):
        Settings(confluence_url=BASE)


def test_empty_quoted_token_counts_as_missing() -> None:
    with pytest.raises(ValidationError, match="CONFLUENCE_TOKEN"):
        Settings(confluence_url=BASE, confluence_token='""')


def test_env_vars_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONFLUENCE_URL", BASE)
    monkeypatch.setenv("CONFLUENCE_TOKEN", "'quoted'")
    monkeypatch.setenv("CONFLUENCE_READ_ONLY", "true")
    s = Settings()  # type: ignore[call-arg]
    assert s.confluence_token == "quoted"
    assert s.confluence_read_only is True


def test_custom_headers_parsing() -> None:
    s = make_settings(confluence_custom_headers="X-A=1, X-B=a=b,broken,=novalue")
    assert s.get_custom_headers() == {"X-A": "1", "X-B": "a=b"}


def test_redacted_hides_secrets() -> None:
    s = make_settings(confluence_custom_headers="X-Secret=zzz")
    text = repr(s.redacted())
    assert "secret-token" not in text
    assert "zzz" not in text
    assert s.redacted()["auth_method"] == "token"


def test_validation_error_does_not_echo_password() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc:
        Settings(confluence_url=BASE, confluence_password="SuperSecret123")
    assert "SuperSecret123" not in str(exc.value)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('abc"', 'abc"'),
        ("'abc", "'abc"),
        ('"abc"', "abc"),
        ("'abc'", "abc"),
        ('""abc""', '"abc"'),
        ("\"abc'", "\"abc'"),
        (' "abc" ', "abc"),
    ],
)
def test_unquote_strips_one_matching_pair(raw: str, expected: str) -> None:
    s = make_settings(confluence_token=None, confluence_username="u", confluence_password=raw)
    assert s.confluence_password == expected


def test_compose_passes_timeout() -> None:
    from pathlib import Path

    compose = (Path(__file__).parent.parent / "docker-compose.yml").read_text()
    assert "CONFLUENCE_TIMEOUT_SECONDS=${CONFLUENCE_TIMEOUT_SECONDS:-30}" in compose


def test_ca_bundle_path_must_exist(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="CONFLUENCE_CA_BUNDLE"):
        make_settings(confluence_ca_bundle=str(tmp_path / "missing.pem"))


def test_ca_bundle_quotes_stripped(tmp_path: Path) -> None:
    bundle = tmp_path / "ca.pem"
    bundle.write_text("x")
    s = make_settings(confluence_ca_bundle=f'"{bundle}"')
    assert s.confluence_ca_bundle == str(bundle)
    assert s.redacted()["ca_bundle"] == str(bundle)


def test_ca_bundle_defaults_to_none() -> None:
    assert make_settings().confluence_ca_bundle is None


def test_compose_passes_ca_bundle() -> None:
    compose = (Path(__file__).parent.parent / "docker-compose.yml").read_text()
    assert "CONFLUENCE_CA_BUNDLE=${CONFLUENCE_CA_BUNDLE:-}" in compose

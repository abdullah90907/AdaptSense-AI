import pytest
from fastapi import HTTPException

from app.credentials import groq_key


@pytest.fixture
def keyfile(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setattr("app.credentials.ENV_PATH", path)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    return path


def test_dotenv_bom_crlf_quoted_key_without_expansion(keyfile):
    keyfile.write_text('\ufeff# comment\r\nGROQ_API_KEY="gsk_controlled_not_real"\r\n', encoding="utf-8")
    assert groq_key() == "gsk_controlled_not_real"


def test_environment_takes_priority(keyfile, monkeypatch):
    keyfile.write_text('GROQ_API_KEY=gsk_file_dummy\n')
    monkeypatch.setenv("GROQ_API_KEY", "gsk_environment_dummy")
    assert groq_key() == "gsk_environment_dummy"


@pytest.mark.parametrize("contents", ['GROQ_API_KEY=gsk_bad key', 'GROQ_API_KEY=wrongprefix',
    'GROQ_API_KEY="gsk_unclosed', 'GROQ_API_KEY=gsk_one\nGROQ_API_KEY=gsk_two'])
def test_invalid_or_ambiguous_credentials_fail_locally(keyfile, contents):
    keyfile.write_text(contents)
    with pytest.raises(HTTPException) as exc:
        groq_key()
    assert exc.value.status_code == 503
    assert "gsk_" not in str(exc.value.detail)


def test_unquoted_comments_export_and_missing_key(keyfile):
    assert groq_key() == ""
    keyfile.write_text('export GROQ_API_KEY=gsk_controlled_not_real # comment\nUNRELATED=${GROQ_API_KEY}')
    assert groq_key() == "gsk_controlled_not_real"

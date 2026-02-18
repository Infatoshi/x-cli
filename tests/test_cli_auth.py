"""Tests for OAuth2 auth CLI commands."""

from pathlib import Path

from click.testing import CliRunner

from x_cli.cli import cli


def test_auth_status_not_logged_in(monkeypatch):
    monkeypatch.setattr("x_cli.cli.load_env_files", lambda: None)
    monkeypatch.delenv("X_OAUTH2_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("X_OAUTH2_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("X_OAUTH2_EXPIRES_AT", raising=False)

    runner = CliRunner()
    result = runner.invoke(cli, ["auth", "status"])
    assert result.exit_code == 0
    assert "OAuth2: not logged in" in result.output


def test_auth_login_requires_client_id(monkeypatch):
    monkeypatch.setattr("x_cli.cli.load_env_files", lambda: None)
    monkeypatch.delenv("X_OAUTH2_CLIENT_ID", raising=False)

    runner = CliRunner()
    result = runner.invoke(cli, ["auth", "login"])
    assert result.exit_code != 0
    assert "Missing env var X_OAUTH2_CLIENT_ID" in result.output


def test_auth_login_success(monkeypatch):
    monkeypatch.setattr("x_cli.cli.load_env_files", lambda: None)
    monkeypatch.setenv("X_OAUTH2_CLIENT_ID", "client-123")
    monkeypatch.setattr("x_cli.cli.generate_code_verifier", lambda: "verifier-1")
    monkeypatch.setattr("x_cli.cli.generate_state", lambda: "state-1")
    monkeypatch.setattr("x_cli.cli.generate_code_challenge", lambda _: "challenge-1")
    monkeypatch.setattr("x_cli.cli.build_authorization_url", lambda **kwargs: "https://auth.example")
    monkeypatch.setattr("x_cli.cli.extract_code_from_redirect_url", lambda *_: "code-1")
    captured = {}

    def fake_exchange(http, **kwargs):
        captured.update(kwargs)
        return {"access_token": "a1", "refresh_token": "r1", "expires_in": 3600}

    monkeypatch.setattr(
        "x_cli.cli.exchange_code_for_token",
        fake_exchange,
    )

    saved = {}

    def fake_persist(path, *, access_token, refresh_token, expires_at):
        saved["path"] = path
        saved["access_token"] = access_token
        saved["refresh_token"] = refresh_token
        saved["expires_at"] = expires_at

    monkeypatch.setattr("x_cli.cli.persist_oauth2_tokens", fake_persist)
    monkeypatch.setattr("x_cli.cli.get_config_env_path", lambda: Path("/tmp/fake.env"))

    runner = CliRunner()
    result = runner.invoke(cli, ["auth", "login"], input="https://example.com/oauth/callback?code=x&state=y\n")
    assert result.exit_code == 0
    assert "OAuth2 login successful" in result.output
    assert saved["path"] == Path("/tmp/fake.env")
    assert saved["access_token"] == "a1"
    assert saved["refresh_token"] == "r1"
    assert isinstance(saved["expires_at"], int)
    assert captured["client_secret"] is None


def test_auth_login_401_hints_client_secret(monkeypatch):
    monkeypatch.setattr("x_cli.cli.load_env_files", lambda: None)
    monkeypatch.setenv("X_OAUTH2_CLIENT_ID", "client-123")
    monkeypatch.delenv("X_OAUTH2_CLIENT_SECRET", raising=False)
    monkeypatch.setattr("x_cli.cli.generate_code_verifier", lambda: "verifier-1")
    monkeypatch.setattr("x_cli.cli.generate_state", lambda: "state-1")
    monkeypatch.setattr("x_cli.cli.generate_code_challenge", lambda _: "challenge-1")
    monkeypatch.setattr("x_cli.cli.build_authorization_url", lambda **kwargs: "https://auth.example")
    monkeypatch.setattr("x_cli.cli.extract_code_from_redirect_url", lambda *_: "code-1")
    monkeypatch.setattr(
        "x_cli.cli.exchange_code_for_token",
        lambda http, **kwargs: (_ for _ in ()).throw(
            RuntimeError("OAuth2 token request failed (HTTP 401): Missing valid authorization header")
        ),
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["auth", "login"], input="https://example.com/oauth/callback?code=x&state=y\n")
    assert result.exit_code != 0
    assert "Set X_OAUTH2_CLIENT_SECRET" in result.output


def test_auth_logout_clears_tokens(monkeypatch):
    cleared = {"called": False}

    def fake_clear(path):
        cleared["called"] = True
        assert str(path).endswith("/.config/x-cli/.env")

    monkeypatch.setattr("x_cli.cli.clear_oauth2_tokens", fake_clear)

    runner = CliRunner()
    result = runner.invoke(cli, ["auth", "logout"])
    assert result.exit_code == 0
    assert cleared["called"] is True

from app.config import Settings


def _settings(monkeypatch, **env):
    for k in ("ADMIN_IDS", "TIMEZONE", "SLOT_STEP_MIN", "CANCEL_DEADLINE_HOURS",
              "DATABASE_URL", "GSHEETS_CREDENTIALS_PATH", "GSHEETS_SPREADSHEET_ID"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("BOT_TOKEN", "t")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return Settings(_env_file=None)


def test_admin_ids_parsed_from_csv(monkeypatch):
    assert _settings(monkeypatch, ADMIN_IDS="1, 2").admin_ids == [1, 2]


def test_admin_ids_empty_string(monkeypatch):
    assert _settings(monkeypatch, ADMIN_IDS="").admin_ids == []


def test_defaults(monkeypatch):
    s = _settings(monkeypatch)
    assert s.admin_ids == []
    assert s.timezone == "Europe/Moscow"
    assert s.slot_step_min == 30
    assert s.cancel_deadline_hours == 2
    assert s.database_url == "sqlite+aiosqlite:///./data/bookings.db"
    assert s.gsheets_credentials_path is None
    assert s.gsheets_spreadsheet_id is None

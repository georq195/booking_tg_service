from pathlib import Path

from app.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parent.parent / ".env.example"


def _names_in_env_example() -> set[str]:
    names = set()
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        names.add(line.partition("=")[0].strip())
    return names


def test_env_example_matches_settings_fields():
    expected = {name.upper() for name in Settings.model_fields}
    assert _names_in_env_example() == expected


def test_env_example_has_no_real_secrets():
    values = dict(
        line.partition("=")[::2]
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    )
    assert values["BOT_TOKEN"].strip() == "123456:replace-me"
    assert values["GSHEETS_CREDENTIALS_PATH"].strip() == ""
    assert values["GSHEETS_SPREADSHEET_ID"].strip() == ""

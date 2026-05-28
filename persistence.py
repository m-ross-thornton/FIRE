import json
import pathlib

SETTINGS_FILE = pathlib.Path("fire_settings.json")

_DEFAULTS = {
    "current_age": 40,
    "death_age": 95,
    "retirement_age": 47,
    "brokerage_balance": 100_000,
    "retirement_balance": 400_000,
    "return_pre": 7.0,           # stored as percent (7.0 == 7%)
    "return_post": 5.0,
    "early_withdrawal_rate": 35.0,
    "events": [],
}


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text())
            return {**_DEFAULTS, **data}
        except Exception:
            pass
    return dict(_DEFAULTS)


def save_settings(settings: dict) -> None:
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2))

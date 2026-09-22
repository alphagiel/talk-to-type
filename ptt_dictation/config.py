"""Saves and loads app settings, like which key to hold and which model to use."""
import json
import os

CONFIG_DIR = os.path.expanduser("~/Library/Application Support/PTTDictation")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

# Keys you can hold to talk, and what to call them in the menu.
# "fn" needs a special workaround since normal key-tracking can't see it reliably on Mac.
# "right_option" and "right_command" work fine with normal key-tracking.
#
# Escape is deliberately never in here -- it's reserved globally to
# force-cancel a stuck recording/transcription (see main.py's _on_escape),
# so it can never also be assigned as the push-to-talk key.
HOTKEY_LABELS = {
    "fn": "Fn",
    "right_option": "Right Option",
    "right_command": "Right Command",
}

DEFAULT_CONFIG = {
    "hotkey": "right_option",
    "model_size": "small.en",
    "min_hold_ms": 150,
    "max_record_seconds": 90,
}


def load_config() -> dict:
    """Load settings from disk. Fill in defaults for anything missing."""
    config = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                on_disk = json.load(f)
            if isinstance(on_disk, dict):
                config.update(on_disk)
        except (json.JSONDecodeError, OSError):
            pass
    # Guard against a hand-edited (or otherwise corrupted) config.json
    # naming a hotkey that doesn't exist -- most importantly "escape",
    # which is reserved for cancel and must never be assignable here.
    if config.get("hotkey") not in HOTKEY_LABELS:
        config["hotkey"] = DEFAULT_CONFIG["hotkey"]
    return config


def save_config(config: dict) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)

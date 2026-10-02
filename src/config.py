"""Configuration for Real-time Meeting Assistant."""
import os
import json
from pathlib import Path
from typing import Any, Dict


def load_config(config_path: str = "config.json") -> Dict[str, Any]:
    """Load configuration from JSON file."""
    if not os.path.exists(config_path):
        print(f"Config file not found: {config_path}")
        return get_default_config()

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        return get_default_config()


def get_default_config() -> Dict[str, Any]:
    """Return default configuration."""
    return {
        "llm": {
            "provider": "anthropic",
            "model": "claude-3-5-haiku-20241022",
            "api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
        },
        "audio": {
            "input_device": None,
            "sample_rate": 16000,
            "chunk_duration_ms": 100,
        },
        "transcription": {
            "model": "base",
            "language": "cs",
        },
        "ui": {
            "width": 40,
            "transcript_color": "white",
            "suggestion_color": "green",
        },
        "hotkey": {
            "key_combination": "cmd+shift+h",
        },
        "system": {
            "context_window_seconds": 30,
            "llm_timeout_seconds": 3,
            "log_level": "INFO",
        },
    }


def save_config(config: Dict[str, Any], config_path: str = "config.json"):
    """Save configuration to JSON file."""
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print(f"Config saved to {config_path}")

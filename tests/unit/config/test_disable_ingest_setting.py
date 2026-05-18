"""Unit tests for the disable_ingest_with_langflow configuration setting."""

import os
import tempfile
from pathlib import Path
import pytest

from config.config_manager import ConfigManager
from config.settings import get_embedding_model, OPENAI_DEFAULT_EMBEDDING_MODEL


def test_disable_ingest_default(monkeypatch):
    """Verify that disable_ingest_with_langflow defaults to False when no env var is present."""
    monkeypatch.delenv("DISABLE_INGEST_WITH_LANGFLOW", raising=False)
    with tempfile.TemporaryDirectory() as tmp:
        cfg_file = Path(tmp) / "config.yaml"
        cm = ConfigManager(config_file=str(cfg_file))
        config = cm.load_config()
        assert config.knowledge.disable_ingest_with_langflow is False


def test_disable_ingest_env_override(monkeypatch):
    """Verify that DISABLE_INGEST_WITH_LANGFLOW env var sets the default value of the setting."""
    monkeypatch.setenv("DISABLE_INGEST_WITH_LANGFLOW", "true")
    with tempfile.TemporaryDirectory() as tmp:
        cfg_file = Path(tmp) / "config.yaml"
        cm = ConfigManager(config_file=str(cfg_file))
        config = cm.load_config()
        assert config.knowledge.disable_ingest_with_langflow is True

    monkeypatch.setenv("DISABLE_INGEST_WITH_LANGFLOW", "1")
    with tempfile.TemporaryDirectory() as tmp:
        cfg_file = Path(tmp) / "config.yaml"
        cm = ConfigManager(config_file=str(cfg_file))
        config = cm.load_config()
        assert config.knowledge.disable_ingest_with_langflow is True

    monkeypatch.setenv("DISABLE_INGEST_WITH_LANGFLOW", "false")
    with tempfile.TemporaryDirectory() as tmp:
        cfg_file = Path(tmp) / "config.yaml"
        cm = ConfigManager(config_file=str(cfg_file))
        config = cm.load_config()
        assert config.knowledge.disable_ingest_with_langflow is False


def test_disable_ingest_preserves_on_save(monkeypatch):
    """Verify that manual updates are persisted to yaml file and not overridden by env var on subsequent loads."""
    monkeypatch.setenv("DISABLE_INGEST_WITH_LANGFLOW", "false")
    with tempfile.TemporaryDirectory() as tmp:
        cfg_file = Path(tmp) / "config.yaml"
        cm = ConfigManager(config_file=str(cfg_file))
        config = cm.load_config()
        assert config.knowledge.disable_ingest_with_langflow is False

        # Manually edit it to True
        config.knowledge.disable_ingest_with_langflow = True
        config.edited = True
        cm.save_config_file(config)

        # Reload configuration
        cm2 = ConfigManager(config_file=str(cfg_file))
        config2 = cm2.load_config()
        assert config2.knowledge.disable_ingest_with_langflow is True

        # Even if environment variable is set to False, once edited=True, the setting is preserved
        monkeypatch.setenv("DISABLE_INGEST_WITH_LANGFLOW", "false")
        config3 = cm2.load_config()
        assert config3.knowledge.disable_ingest_with_langflow is True

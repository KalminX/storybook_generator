from pathlib import Path

import pytest

from src.config import ConfigError, find_config_file, load_api_key, load_config

PROJECT_DIR = Path(__file__).resolve().parent.parent

MINIMAL = """
provider:
  text_model: text-model
  image_model: image-model
"""


def write(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


def test_example_config_is_valid():
    config = load_config(PROJECT_DIR / "config.example.yaml")
    assert config.provider.text_model
    assert config.provider.image_model
    assert config.paths.input_file == PROJECT_DIR / "input" / "stories.txt"


def test_minimal_config_uses_defaults_and_resolves_relative_paths(tmp_path):
    config = load_config(write(tmp_path / "config.yaml", MINIMAL))
    assert config.retry.max_attempts == 5
    assert config.paths.output_directory == tmp_path / "output"
    assert config.paths.style_file == tmp_path / "input" / "style_spec.md"
    assert config.source == tmp_path / "config.yaml"


def test_absolute_paths_kept(tmp_path):
    text = MINIMAL + f"paths:\n  output_directory: {tmp_path / 'elsewhere'}\n"
    config = load_config(write(tmp_path / "config.yaml", text))
    assert config.paths.output_directory == tmp_path / "elsewhere"


@pytest.mark.parametrize(
    "text, message",
    [
        ("provider: [unclosed", "not valid YAML"),
        ("- a list", "mapping"),
        ("retry:\n  max_attempts: 3\n", "provider"),
        (MINIMAL + "retry:\n  max_attempt: 3\n", "max_attempt"),  # typo is reported
        (MINIMAL + "retry:\n  initial_delay: 10\n  max_delay: 1\n", "max_delay"),
        (MINIMAL + "logging:\n  level: LOUD\n", "log level"),
    ],
)
def test_invalid_configs_raise_config_error(tmp_path, text, message):
    with pytest.raises(ConfigError, match=message):
        load_config(write(tmp_path / "config.yaml", text))


def test_missing_config_file(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.yaml")


def test_find_config_prefers_user_config(tmp_path):
    write(tmp_path / "config.example.yaml", MINIMAL)
    assert find_config_file(tmp_path).name == "config.example.yaml"
    write(tmp_path / "config.yaml", MINIMAL)
    assert find_config_file(tmp_path).name == "config.yaml"


def test_find_config_errors_when_none(tmp_path):
    with pytest.raises(ConfigError):
        find_config_file(tmp_path)


def test_api_key_from_environment(monkeypatch):
    monkeypatch.setenv("TEST_KEY_VAR", "  secret-value ")
    assert load_api_key("TEST_KEY_VAR") == "secret-value"


def test_api_key_from_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_KEY_VAR", raising=False)
    env_file = write(tmp_path / ".env", "TEST_KEY_VAR=from-file\n")
    assert load_api_key("TEST_KEY_VAR", env_file) == "from-file"
    monkeypatch.delenv("TEST_KEY_VAR")  # load_dotenv mutates os.environ


def test_missing_api_key_message_does_not_leak(monkeypatch, tmp_path):
    monkeypatch.delenv("TEST_KEY_VAR", raising=False)
    with pytest.raises(ConfigError, match="TEST_KEY_VAR is not set"):
        load_api_key("TEST_KEY_VAR", tmp_path / "missing.env")


def test_images_defaults_and_validation(tmp_path):
    config = load_config(write(tmp_path / "config.yaml", MINIMAL))
    assert config.images.aspect_ratio == "1:1"
    assert config.images.reference_images == 1
    blank = MINIMAL + "images:\n  image_size:\n  aspect_ratio: '3:4'\n"
    config = load_config(write(tmp_path / "config.yaml", blank))
    assert config.images.image_size is None
    assert config.images.aspect_ratio == "3:4"
    for bad in ("aspect_ratio: square", "reference_images: 9"):
        with pytest.raises(ConfigError):
            load_config(write(tmp_path / "config.yaml", MINIMAL + f"images:\n  {bad}\n"))

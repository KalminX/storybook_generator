"""Application configuration.

Non-secret settings come from a YAML file; secrets come from environment
variables (optionally loaded from a ``.env`` file). Nothing in here is global:
callers load an ``AppConfig`` once and pass it (or parts of it) down.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

CONFIG_FILENAME = "config.yaml"
EXAMPLE_CONFIG_FILENAME = "config.example.yaml"


class ConfigError(Exception):
    """Raised when configuration is missing or invalid."""


class _Section(BaseModel):
    # Reject unknown keys so typos in config.yaml are reported, not ignored.
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderConfig(_Section):
    name: str = "gemini"
    api_key_env: str = "GEMINI_API_KEY"
    text_model: str = Field(min_length=1)
    image_model: str = Field(min_length=1)
    request_timeout_seconds: float = Field(default=180, gt=0)


class RetryConfig(_Section):
    max_attempts: int = Field(default=5, ge=1, le=20)
    initial_delay: float = Field(default=2, ge=0)
    max_delay: float = Field(default=30, ge=0)

    @field_validator("max_delay")
    @classmethod
    def _max_not_below_initial(cls, value: float, info) -> float:
        initial = info.data.get("initial_delay")
        if initial is not None and value < initial:
            raise ValueError("max_delay must be >= initial_delay")
        return value


class PathsConfig(_Section):
    input_file: Path = Path("input/stories.txt")
    style_file: Path = Path("input/style_spec.md")
    output_directory: Path = Path("output")
    log_directory: Path = Path("logs")

    def resolved(self, base_dir: Path) -> PathsConfig:
        """Return a copy with relative paths made absolute against ``base_dir``."""
        def resolve(p: Path) -> Path:
            p = p.expanduser()
            return p if p.is_absolute() else (base_dir / p).resolve()

        return PathsConfig(
            input_file=resolve(self.input_file),
            style_file=resolve(self.style_file),
            output_directory=resolve(self.output_directory),
            log_directory=resolve(self.log_directory),
        )


class ImagesConfig(_Section):
    # Passed to the image model; None means the model's default.
    aspect_ratio: str | None = "1:1"
    image_size: str | None = None
    # How many of the story's first finished illustrations to send along with
    # each new page request as a visual reference (0 disables).
    reference_images: int = Field(default=1, ge=0, le=4)

    @field_validator("aspect_ratio")
    @classmethod
    def _ratio_format(cls, value: str | None) -> str | None:
        if value is not None:
            parts = value.split(":")
            if len(parts) != 2 or not all(p.isdigit() and int(p) > 0 for p in parts):
                raise ValueError(f"aspect_ratio must look like '3:4', got {value!r}")
        return value


class PdfConfig(_Section):
    page_width_mm: float = Field(default=203.2, gt=0)
    page_height_mm: float = Field(default=203.2, gt=0)
    margin_mm: float = Field(default=12, ge=0)
    font_name: str = "Helvetica"
    title_font_name: str = "Helvetica-Bold"
    font_size: float = Field(default=16, gt=0)
    title_font_size: float = Field(default=32, gt=0)
    line_spacing: float = Field(default=1.35, gt=0)
    show_page_numbers: bool = True
    # Fraction of the page height below the illustration reserved for text.
    text_area_ratio: float = Field(default=0.3, gt=0, lt=1)
    # Long text shrinks down to this size before it is allowed to overflow.
    min_font_size: float = Field(default=10, gt=0)
    cover_illustration: bool = True
    # Optional .ttf files; when set they replace font_name / title_font_name.
    font_file: Path | None = None
    title_font_file: Path | None = None
    text_color: str = "#000000"
    background_color: str = "#FFFFFF"
    # How illustrations are stored inside the PDF. "jpeg" keeps files small;
    # "png" is lossless but roughly 10x larger. Originals in pages/ are always PNG.
    embed_images_as: Literal["jpeg", "png"] = "jpeg"
    jpeg_quality: int = Field(default=90, ge=50, le=100)

    @field_validator("text_color", "background_color")
    @classmethod
    def _hex_color(cls, value: str) -> str:
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
            raise ValueError(f"colors must look like '#1A2B3C', got {value!r}")
        return value

    def resolved(self, base_dir: Path) -> PdfConfig:
        """Return a copy with relative font paths made absolute against ``base_dir``."""
        def resolve(p: Path | None) -> Path | None:
            if p is None:
                return None
            p = p.expanduser()
            return p if p.is_absolute() else (base_dir / p).resolve()

        return self.model_copy(
            update={
                "font_file": resolve(self.font_file),
                "title_font_file": resolve(self.title_font_file),
            }
        )


class LoggingConfig(_Section):
    level: str = "INFO"

    @field_validator("level")
    @classmethod
    def _valid_level(cls, value: str) -> str:
        value = value.upper()
        if value not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"unknown log level {value!r}")
        return value


class AppConfig(_Section):
    provider: ProviderConfig
    retry: RetryConfig = RetryConfig()
    paths: PathsConfig = PathsConfig()
    images: ImagesConfig = ImagesConfig()
    pdf: PdfConfig = PdfConfig()
    logging: LoggingConfig = LoggingConfig()
    # Path of the file this config was loaded from (informational).
    source: Path | None = None


def find_config_file(project_dir: Path) -> Path:
    """Prefer the user's config.yaml, fall back to the shipped example."""
    for name in (CONFIG_FILENAME, EXAMPLE_CONFIG_FILENAME):
        candidate = project_dir / name
        if candidate.is_file():
            return candidate
    raise ConfigError(
        f"No configuration file found. Expected {CONFIG_FILENAME} or "
        f"{EXAMPLE_CONFIG_FILENAME} in {project_dir}."
    )


def load_config(path: Path) -> AppConfig:
    """Load and validate a YAML config file. Relative paths resolve against its folder."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Configuration file {path} is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"Configuration file {path} must contain a mapping of settings.")

    try:
        config = AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"Invalid configuration in {path}:\n{exc}") from exc

    base_dir = path.resolve().parent
    return config.model_copy(
        update={
            "paths": config.paths.resolved(base_dir),
            "pdf": config.pdf.resolved(base_dir),
            "source": path.resolve(),
        }
    )


def load_api_key(env_var: str, env_file: Path | None = None) -> str:
    """Return the API key from the environment, loading ``env_file`` first if given.

    Values already present in the real environment take precedence over ``.env``.
    """
    if env_file is not None and env_file.is_file():
        load_dotenv(env_file, override=False)
    key = os.environ.get(env_var, "").strip()
    if not key:
        raise ConfigError(
            f"{env_var} is not set. Put your key in the .env file as {env_var}=your-key"
        )
    return key

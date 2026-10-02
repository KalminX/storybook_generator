"""Composition root: the one place that wires concrete classes together."""

from __future__ import annotations

from functools import partial

from src.config import AppConfig, RetryConfig
from src.generation.image_generator import ImageGenerator
from src.generation.story_generator import StoryGenerator
from src.infrastructure.retry import RetryPolicy
from src.pipeline.story_pipeline import StoryPipeline
from src.providers.factory import create_providers
from src.rendering.pdf_renderer import render_storybook
from src.utils.inputs import load_style_spec


def retry_policy(config: RetryConfig) -> RetryPolicy:
    return RetryPolicy(
        max_attempts=config.max_attempts,
        initial_delay=config.initial_delay,
        max_delay=config.max_delay,
    )


def build_pipeline(config: AppConfig, api_key: str) -> StoryPipeline:
    providers = create_providers(config.provider, api_key)
    style_spec = load_style_spec(config.paths.style_file)
    return StoryPipeline(
        story_generator=StoryGenerator(providers.text, style_spec),
        image_generator=ImageGenerator(
            providers.image,
            style_spec,
            aspect_ratio=config.images.aspect_ratio,
            image_size=config.images.image_size,
        ),
        renderer=partial(render_storybook, config=config.pdf),
        retry_policy=retry_policy(config.retry),
        output_directory=config.paths.output_directory,
        reference_images=config.images.reference_images,
    )

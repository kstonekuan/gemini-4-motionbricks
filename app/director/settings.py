"""Portable director configuration loaded from arguments, environment and .env."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, StringConstraints, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_MODEL = "gemini-4-argon"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class DirectorSettings(BaseSettings):
    """Explicit values override environment variables, which override local .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MOTIONBRICKS_",
        populate_by_name=True,
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    gemini_api_key: SecretStr | None = Field(
        default=None, validation_alias="GEMINI_API_KEY"
    )
    gemini_model: NonEmptyText = Field(
        default=DEFAULT_MODEL, validation_alias="GEMINI_MODEL"
    )
    scene_images: bool = True
    host: NonEmptyText = "127.0.0.1"
    port: Annotated[int, Field(ge=1, le=65535)] = 6090
    assets: Path = REPOSITORY_ROOT / "web/dist"

    @field_validator("gemini_api_key", mode="before")
    @classmethod
    def normalize_optional_api_key(cls, value: object) -> object:
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        if isinstance(value, str):
            return value.strip() or None
        return value

    def require_api_key(self) -> str:
        """The gym can load without a credential; planning requires one."""
        if self.gemini_api_key is None:
            raise ValueError(
                "Set GEMINI_API_KEY in the environment or .env before directing the character."
            )
        return self.gemini_api_key.get_secret_value()

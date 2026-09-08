from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    host: str = "127.0.0.1"
    port: int = Field(ge=1, le=65535)
    data_dir: Path
    generation_config: Path | None
    max_concurrency: int = Field(ge=1)
    max_queued: int = Field(ge=0)
    max_upload_bytes: int = Field(gt=0)
    max_request_bytes: int = Field(gt=0)
    max_prompt_chars: int = Field(gt=0)
    max_image_pixels: int = Field(gt=0)

    @model_validator(mode="after")
    def request_limit(self):
        if self.max_request_bytes <= self.max_upload_bytes:
            raise ValueError("max_request_bytes must leave room for multipart metadata")
        return self


def load_config(path: Path) -> Config:
    values = yaml.safe_load(path.read_text())
    if not isinstance(values, dict):
        raise ValueError("Root configuration must be a YAML mapping")
    for key in ("data_dir", "generation_config"):
        if key in values and values[key] is not None:
            values[key] = (path.parent / values[key]).resolve()
    return Config.model_validate(values)

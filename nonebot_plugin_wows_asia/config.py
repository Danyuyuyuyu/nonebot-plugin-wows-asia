from typing import Literal

from pydantic import BaseModel, Field, SecretStr


class Config(BaseModel):
    # Missing application_id must not prevent NoneBot from starting.
    wows_application_id: SecretStr = SecretStr("")
    wows_timeout_seconds: float = Field(default=15, ge=1, le=60)
    wows_cache_seconds: int = Field(default=60, ge=0, le=3600)
    wows_command_priority: int = Field(default=10, ge=1)
    # Card output. "text" disables the browser entirely.
    wows_render_mode: Literal["image", "text"] = "image"
    wows_render_scale: float = Field(default=1.5, ge=1, le=3)
    wows_browser_path: str = ""
    # Snapshot tracking for recent stats / per-battle rows.
    wows_poll_minutes: int = Field(default=10, ge=3, le=720)
    wows_track_days: int = Field(default=14, ge=1, le=90)
    wows_max_tracked: int = Field(default=200, ge=1, le=5000)
    wows_record_days: int = Field(default=30, ge=15, le=365)
    wows_min_battles: int = Field(default=50, ge=0, le=1000)

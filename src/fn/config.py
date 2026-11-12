"""Settings for one fn process, read from the environment."""
import os
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, SecretStr

from fn.contracts import LLMMode

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    root: Path = ROOT
    var_dir: Path = ROOT / "var"
    fixtures_dir: Path = ROOT / "tests" / "fixtures" / "llm"
    mode: Literal["local"] = "local"
    host: str = "127.0.0.1"
    port: int = 8765
    env: Literal["dev", "test"] = "dev"
    llm_mode: LLMMode = "live"
    http_mode: Literal["live", "replay"] = "live"
    openalex_api_key: SecretStr | None = None
    parallel_api_key: SecretStr | None = None
    apify_token: SecretStr | None = None
    linkedin_live: bool = False

    @property
    def db_path(self) -> Path:
        return self.var_dir / "fn.sqlite3"

    def secrets(self) -> list[str]:
        """Every non-empty secret value, for redact()."""
        values = [getattr(self, name) for name in type(self).model_fields]
        return [v.get_secret_value() for v in values if isinstance(v, SecretStr) and v.get_secret_value()]


def keychain(name: str) -> str | None:
    """Read a secret from the macOS Keychain; None when it is missing or the lookup fails."""
    try:
        done = subprocess.run(
            ["security", "find-generic-password", "-a", os.environ.get("USER", ""), "-s", name, "-w"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip() or None


def from_env() -> Settings:
    """Settings from FN_* env vars; each key from the env var of its field name in capitals, else the Keychain."""
    env = os.environ

    def secret(name: str) -> str | None:
        return env.get(name) or keychain(name)

    fields = {
        "var_dir": env.get("FN_VAR"),
        "fixtures_dir": env.get("FN_FIXTURES"),
        "host": env.get("FN_HOST"),
        "port": env.get("FN_PORT"),
        "env": env.get("FN_ENV"),
        "llm_mode": env.get("FN_LLM"),
        "http_mode": env.get("FN_HTTP"),
        "openalex_api_key": secret("OPENALEX_API_KEY"),
        "parallel_api_key": secret("PARALLEL_API_KEY"),
        "apify_token": secret("APIFY_TOKEN"),
        "linkedin_live": env.get("FN_LINKEDIN") == "1",
    }
    return Settings(**{k: v for k, v in fields.items() if v is not None})

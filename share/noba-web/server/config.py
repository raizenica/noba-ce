import os
import yaml
from pathlib import Path
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings

CONFIG_PATH = Path(os.path.expanduser("~/.config/noba/config.yaml"))

class WebhookConfig(BaseModel):
    url: str
    method: str = "POST"
    headers: dict = Field(default_factory=dict)

class AutomationConfig(BaseModel):
    allowed_commands: list[str] = Field(default_factory=list)
    webhooks: dict[str, WebhookConfig] = Field(default_factory=dict)

class ServerSettings(BaseSettings):
    model_config = {"extra": "ignore"}
    host: str = "0.0.0.0"
    port: int = 8080
    secret_key: SecretStr = Field(default=SecretStr("CHANGE_ME_IN_PRODUCTION"))
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440
    automation: AutomationConfig = Field(default_factory=AutomationConfig)

    @classmethod
    def load_from_yaml(cls) -> "ServerSettings":
        if not CONFIG_PATH.exists():
            return cls()

        with open(CONFIG_PATH, 'r') as f:
            data = yaml.safe_load(f) or {}

        # Extract web specific config, fallback to empty dict
        web_data = data.get("web", {})

        # Inject secret key if provided in env or yaml
        if "NOBA_SECRET_KEY" in os.environ:
            web_data["secret_key"] = os.environ["NOBA_SECRET_KEY"]

        return cls(**web_data)

# Global singleton for configuration
settings = ServerSettings.load_from_yaml()

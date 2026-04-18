from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://unchained:unchained@postgres:5432/unchained"
    database_url_sync: str = "postgresql://unchained:unchained@postgres:5432/unchained"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # JWT
    jwt_secret_key: str = "change-me-to-a-random-secret-at-least-32-chars"
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = 1440

    # RunPod
    runpod_api_key: str = ""
    runpod_base_url: str = "https://api.runpod.ai/v2"

    # Modal
    modal_token_id: str = ""
    modal_token_secret: str = ""
    modal_environment: str = "main"
    modal_app_prefix: str = "unchained"

    # HuggingFace (for gated models)
    hf_token: str = ""

    # Paddle
    paddle_api_key: str = ""
    paddle_webhook_secret: str = ""
    paddle_environment: str = "sandbox"

    # Rate limits per minute by tier
    rate_limit_free: int = 20
    rate_limit_starter: int = 60
    rate_limit_pro: int = 120
    rate_limit_business: int = 300

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def modal_enabled(self) -> bool:
        return bool(self.modal_token_id and self.modal_token_secret)

    @property
    def modal_secrets_env(self) -> dict[str, str]:
        if not self.modal_enabled:
            return {}
        return {
            "MODAL_TOKEN_ID": self.modal_token_id,
            "MODAL_TOKEN_SECRET": self.modal_token_secret,
        }


settings = Settings()

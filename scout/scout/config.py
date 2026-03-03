from pydantic_settings import BaseSettings


class ScoutSettings(BaseSettings):
    database_url_sync: str = "postgresql://unchained:unchained@postgres:5432/unchained"
    runpod_api_key: str = ""
    runpod_base_url: str = "https://api.runpod.ai/v2"
    hf_token: str = ""
    anthropic_api_key: str = ""

    scout_interval_hours: int = 2
    scout_auto_deploy_min_downloads: int = 1000
    scout_auto_deploy_min_likes: int = 20
    scout_min_downloads: int = 100
    scout_min_likes: int = 5

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = ScoutSettings()

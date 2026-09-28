from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Story Service"
    API_V1_STR: str = "/api/v1"
    DATABASE_URL: str = "sqlite+aiosqlite:///./stories.db"
    LORE_SERVICE_URL: str = "http://127.0.0.1:8001"
    STORAGE_DIR: str = "./storage/texts"
    DEBUG: bool = False

    model_config = SettingsConfigDict(env_prefix="STORY_", env_file=".env", extra="ignore")


settings = Settings()

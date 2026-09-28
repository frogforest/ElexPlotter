from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Lore Service"
    API_V1_STR: str = "/api/v1"
    DATABASE_URL: str = "sqlite+aiosqlite:///./lore.db"
    DEBUG: bool = False

    model_config = SettingsConfigDict(env_prefix="LORE_", env_file=".env", extra="ignore")


settings = Settings()

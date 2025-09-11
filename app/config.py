import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """
    Configuration settings for the application, loaded from environment variables.
    """
    # PostgreSQL Database URL
    # The format is postgresql://user:password@host:port/dbname
    DATABASE_URL: str = (
        f"postgresql://{os.getenv('POSTGRES_USER')}"
        f":{os.getenv('POSTGRES_PASSWORD')}"
        f"@{os.getenv('POSTGRES_HOST')}"
        f":{os.getenv('POSTGRES_PORT')}"
        f"/{os.getenv('POSTGRES_DB')}"
    )

    # Redis URL
    REDIS_HOST: str = os.getenv("REDIS_HOST", "redis")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", 6379))

    class Config:
        # This tells pydantic-settings to load variables from a .env file if present
        # Although Docker Compose's env_file is the primary method here.
        env_file = ".env"

# Instantiate the settings
settings = Settings()
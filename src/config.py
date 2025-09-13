import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """
    Configuration settings for the application, loaded from environment variables.
    """
    # PostgreSQL Database URL
    DATABASE_URL: str = (
        f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
        f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT')}"
        f"/{os.getenv('POSTGRES_DB')}"
    )

    # Redis URL (for Celery Broker)
    REDIS_HOST: str = os.getenv("REDIS_HOST", "redis")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", 6379))
    CELERY_BROKER_URL: str = f"redis://{REDIS_HOST}:{REDIS_PORT}/0"
    CELERY_RESULT_BACKEND: str = f"redis://{REDIS_HOST}:{REDIS_PORT}/0"

    # JWT Secret Key
    SECRET_KEY: str = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"

    # --- ADD THESE NEW SETTINGS ---
    # ChromaDB Settings
    CHROMA_HOST: str = "chroma"
    CHROMA_PORT: int = 8000

    # Embedding Model Configuration
    EMBEDDING_MODEL_NAME: str = "all-MiniLM-L6-v2"

    # Directory for storing uploaded files (inside the container)
    STORAGE_PATH: str = "/storage"

    class Config:
        env_file = ".env"

# Instantiate the settings
settings = Settings()
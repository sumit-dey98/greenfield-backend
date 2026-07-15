from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    # Only consumed by docker-compose.yml (interpolated into the container's DATABASE_URL) -
    # declared here so the app itself doesn't choke on the extra .env key when running natively.
    database_url_docker: Optional[str] = None
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 180
    refresh_token_expire_days: int = 7
    environment: str = "local"
    cors_origins: str = "http://localhost:3000"

    # ---- Admission System ----
    cloudinary_cloud_name: Optional[str] = None
    cloudinary_api_key: Optional[str] = None
    cloudinary_api_secret: Optional[str] = None
    admission_max_file_size_bytes: int = 10240
    admission_max_photo_size_bytes: int = 20480
    admission_max_files: int = 4
    admission_rate_limit_per_hour: int = 5
    admission_rate_limit_per_day: int = 20
    admission_verify_max_attempts: int = 5
    admission_verify_lockout_minutes: int = 30
    captcha_secret_key: Optional[str] = None

    class Config:
        env_file = ".env"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
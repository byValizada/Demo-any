from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import List


class Settings(BaseSettings):
    # App
    APP_NAME: str = "EduAI"
    DEBUG: bool = True
    ALLOWED_ORIGINS: str = "http://localhost:5173"

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_origins(cls, v):
        if isinstance(v, list):
            return ",".join(v)
        return v

    def get_origins(self) -> List[str]:
        origins = [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]
        if self.DEBUG:
            # localhost portları
            for port in range(5170, 5180):
                for host in ("localhost", "127.0.0.1"):
                    origin = f"http://{host}:{port}"
                    if origin not in origins:
                        origins.append(origin)
            # LAN IP-ləri (192.168.x.x, 10.x.x.x, 172.16-31.x.x)
            origins.append("http://10.103.32.24:5173")
            origins.append("http://10.103.32.24:5174")
            origins.append("http://10.103.32.24:5175")
        return origins

    # Database
    DATABASE_URL: str

    # JWT
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Ollama — yerli AI server (pulsuz, GPU ilə)
    OLLAMA_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.1:8b"
    OLLAMA_EMBED_MODEL: str = "nomic-embed-text"

    # RAG — ChromaDB yolu
    RAG_DB_PATH: str = "./rag_db"

    # AI Providers
    GROQ_API_KEY: str = ""
    GEMINI_API_KEY: str = ""

    # Legacy
    HF_TOKEN: str = ""

    # ── E-mail (SMTP) ──
    # Boş qalsa "dev rejim": e-maillər konsola + sent_emails.log faylına yazılır
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@varisacademy.az"
    EMAIL_FROM_NAME: str = "VarisAcademy"
    APP_URL: str = "http://localhost:5173"

    class Config:
        env_file = ".env"


settings = Settings()

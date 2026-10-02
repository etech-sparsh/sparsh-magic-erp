from pydantic_settings import BaseSettings
import os
from dotenv import load_dotenv
from typing import Optional

# Explicitly load .env file (check for both .env and env)
load_dotenv(".env")
load_dotenv("env")

class Settings(BaseSettings):
    MONGODB_URI: str = "mongodb://localhost:27017"
    DATABASE_NAME: str = "sparsh_erp"
    SECRET_KEY: str = "your-secret-key-change-it-in-prod"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # Notification Config
    SMTP_SERVER: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None

    # ── SMTP delivery reliability (app/services/smtp_delivery.py) ──
    # Additive tunables only; none of them change the server, port, STARTTLS or credentials
    # above. Defaults are chosen to sit well inside Gmail's limits, which the previous
    # connection-per-email behaviour blew through (~130 handshakes/minute, 4.8k in one day).
    SMTP_TIMEOUT_SECONDS: int = 30          # socket timeout for connect/login/send
    SMTP_MAX_PER_MINUTE: int = 30           # burst ceiling; 0 disables rate limiting
    SMTP_MAX_PER_DAY: int = 1500            # daily ceiling, under Gmail's ~2000; 0 disables
    SMTP_MAX_RETRIES: int = 3               # attempts per message (1 = no retry)
    SMTP_BACKOFF_BASE_SECONDS: float = 2.0  # delay = base * 2**(attempt-1)
    SMTP_BACKOFF_MAX_SECONDS: float = 30.0  # ceiling for a single backoff wait
    SMTP_MAX_CONSECUTIVE_FAILURES: int = 10 # trip the breaker after this many in a row
    SMTP_FAILURE_COOLDOWN_SECONDS: int = 900  # how long the breaker stays open
    SMTP_IDLE_TIMEOUT_SECONDS: int = 60     # close (and re-probe) a connection idle this long

    # Maytapi (deprecated — replaced by Meta WhatsApp Cloud API below)
    MAYTAPI_PRODUCT_ID: Optional[str] = None
    MAYTAPI_PHONE_ID: Optional[str] = None
    MAYTAPI_TOKEN: Optional[str] = None

    # WhatsApp Cloud API (Meta) — official Business Platform
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = None
    WHATSAPP_BUSINESS_ACCOUNT_ID: Optional[str] = None
    WHATSAPP_ACCESS_TOKEN: Optional[str] = None
    WHATSAPP_API_VERSION: str = "v21.0"
    # Meta App ID — only needed to author templates with an IMAGE/VIDEO/DOCUMENT header, whose
    # sample media must be pushed through the Resumable Upload API to obtain a handle.
    WHATSAPP_APP_ID: Optional[str] = None
    # Local numbers stored without a country code get this prefixed (India = 91).
    WHATSAPP_DEFAULT_COUNTRY_CODE: str = "91"
    # Meta webhook credentials. The APP SECRET signs every callback body (X-Hub-Signature-256)
    # and is the ONLY thing separating a real Meta callback from anyone who guessed the URL —
    # without it configured the Leadership webhook refuses traffic rather than trusting it.
    # The VERIFY TOKEN is the string Meta echoes back during the one-time GET handshake.
    WHATSAPP_APP_SECRET: Optional[str] = None
    WHATSAPP_WEBHOOK_VERIFY_TOKEN: Optional[str] = None

    # OpenAI
    OPENAI_API_KEY: Optional[str] = None
    AUDIO_TRANSCRIPTION_MODEL: str = "gpt-4o-transcribe"
    AUDIO_DIARIZATION_MODEL: str = "gpt-4o-transcribe-diarize"
    AUDIO_ENRICHMENT_MODEL: str = "gpt-4o-mini"
    ENABLE_AUDIO_DIARIZATION: bool = True

    # AWS
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: Optional[str] = None
    S3_BUCKET_NAME: Optional[str] = None

    # ── TEMPORARY: keep accepting uploads while S3 is unreachable ──
    # OFF by default, and deliberately so. Turning it on makes an upload fall back to this
    # server's own disk when S3 refuses, which keeps a form working during an outage or a
    # credential rotation -- at the cost of putting candidate CVs (personal data) on a box
    # that is probably not backed up and definitely is not the system of record.
    #
    # Enable it for a demo or an incident, migrate with
    # `scripts/migrate_local_uploads_to_s3.py`, then turn it off again. Every fallback write
    # is logged at WARNING and every stored key is prefixed `local/`, so what landed here is
    # always countable -- see app/services/local_upload_store.py.
    LOCAL_UPLOAD_FALLBACK: bool = False
    LOCAL_UPLOAD_DIR: str = "var/uploads"
    # How long a link to a locally-stored file stays valid. Mirrors the S3 presign TTL, so
    # callers that hand a URL to a browser behave the same either way.
    LOCAL_UPLOAD_URL_TTL_SECONDS: int = 3600

    # Attachment storage (multi-modal assistant uploads).
    # ATTACHMENT_STORAGE_PROVIDER overrides AssistantConfig.STORAGE_PROVIDER when set
    # ("local" for dev, "s3" for prod). LOCAL_STORAGE_DIR is where the local
    # backend writes raw files (served back via the download route).
    ATTACHMENT_STORAGE_PROVIDER: Optional[str] = None
    LOCAL_STORAGE_DIR: str = "uploads/assistant"

    # Optional explicit ffmpeg location (used for audio/video transcription when
    # the binary isn't on the process PATH). Set either the full binary path or
    # the directory containing it.
    FFMPEG_BINARY: Optional[str] = None
    FFMPEG_DIR: Optional[str] = None

    model_config = {
        "env_file": ".env",
        "extra": "ignore"
    }

settings = Settings()

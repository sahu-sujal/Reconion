from __future__ import annotations

from urllib.parse import quote_plus
from dotenv import load_dotenv
import os

load_dotenv()

DB_DRIVER = os.getenv("DB_DRIVER", "postgresql")
DB_USER = quote_plus(os.getenv("POSTGRES_USER", "postgres"))
DB_PASSWORD = quote_plus(os.getenv("POSTGRES_PASSWORD", ""))
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")
DB_NAME = os.getenv("POSTGRES_DB", "recon")

DATABASE_URL = (
    f"{DB_DRIVER}://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


Base = declarative_base()
BACKEND_DIR = Path(__file__).resolve().parents[2]
BACKEND_DATA_DIR = BACKEND_DIR / "data"
DEFAULT_SQLITE_DB_PATH = BACKEND_DATA_DIR / "fzg.db"


def _normalize_sqlite_url(url: str) -> str:
    raw_url = str(url or "").strip()
    if not raw_url:
        return raw_url
    if raw_url.startswith("sqlite:////"):
        return raw_url
    if not raw_url.startswith("sqlite:///"):
        return raw_url

    body = raw_url[len("sqlite:///"):]
    if not body or body.startswith(":memory:"):
        return raw_url

    path_part, query_sep, query = body.partition("?")
    if os.path.isabs(path_part):
        return raw_url

    normalized_path = (BACKEND_DIR / path_part).resolve()
    normalized_url = f"sqlite:///{normalized_path.as_posix()}"
    if query_sep:
        normalized_url = f"{normalized_url}?{query}"
    return normalized_url


def get_database_url() -> str:
    # 默认指向本地 SQLite，生产可通过 DATABASE_URL 切到 MySQL。
    configured_url = os.getenv("DATABASE_URL", "").strip()
    if not configured_url:
        BACKEND_DATA_DIR.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{DEFAULT_SQLITE_DB_PATH.as_posix()}"
    return _normalize_sqlite_url(configured_url)


def create_engine_and_session():
    url = get_database_url()
    connect_args = {}
    if url.startswith("sqlite"):
        if url.startswith("sqlite:///") and not url.startswith("sqlite:////") and ":memory:" not in url:
            BACKEND_DATA_DIR.mkdir(parents=True, exist_ok=True)
        connect_args = {"check_same_thread": False}

    engine = create_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)
    return engine, session_factory


ENGINE, SessionLocal = create_engine_and_session()


@contextmanager
def get_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

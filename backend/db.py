import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


Base = declarative_base()


def get_database_url() -> str:
    # 默认指向本地 SQLite，生产可通过 DATABASE_URL 切到 MySQL。
    return os.getenv("DATABASE_URL", "sqlite:///data/fzg.db")


def create_engine_and_session():
    url = get_database_url()
    connect_args = {}
    if url.startswith("sqlite"):
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

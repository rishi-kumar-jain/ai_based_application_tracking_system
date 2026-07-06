import re

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.core.config import Settings

# def build_engine_and_sessionmaker(settings: Settings):
#     engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
#     SessionMaker = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
#     return engine, SessionMaker

def ensure_schema(engine, schema_name: str):
    # Only allow letters, numbers, underscores — nothing else
    if not re.match(r'^[a-zA-Z0-9_]+$', schema_name):
        raise ValueError(f"Invalid schema name: {schema_name}")
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))




def build_engine_and_sessionmaker(settings: Settings):
    engine = create_engine(
        settings.database_url,
        # --- Pool tuning for serverless ---
        pool_size=2,               # Keep small – each Lambda instance pools its own connections
        max_overflow=2,            # Allow a few extra under burst
        pool_recycle=600,          # Recycle connections every 10 minutes (before DB idle timeout)
        pool_pre_ping=True,        # Keep – safety against dropped connections (adds ~1ms when warm)
        # --------------------------------
        future=True,
    )
    SessionMaker = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return engine, SessionMaker

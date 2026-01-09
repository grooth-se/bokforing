"""
SQLAlchemy bas och databasanslutning
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import DATABASE_URL

# Skapa engine
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}  # Krävs för SQLite
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Bas för alla modeller
Base = declarative_base()


def get_db():
    """Dependency för att få databas-session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initiera databasen och skapa alla tabeller"""
    Base.metadata.create_all(bind=engine)

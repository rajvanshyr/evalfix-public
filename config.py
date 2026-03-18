import os
from dotenv import load_dotenv

load_dotenv()

def _database_url():
    url = os.environ.get("DATABASE_URL", "sqlite:///evalfix.db")
    # Heroku provides postgres:// but SQLAlchemy requires postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url

class Config:
    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

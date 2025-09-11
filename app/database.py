#### File: `app/database.py`

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from config import settings

# Create the SQLAlchemy engine
# This engine is the entry point to our database.
engine = create_engine(settings.DATABASE_URL)

# Each instance of the SessionLocal class will be a new database session.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# We will inherit from this class to create each of the ORM models.
Base = declarative_base()
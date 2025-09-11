import redis
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import SessionLocal, engine,Base, get_db
from config import settings


app = FastAPI(
    title="Lexi-Graph API",
    description="Backend services for the Lexi-Graph e-discovery platform.",
    version="0.1.0",
)

@app.on_event("startup")
def startup():
    from models import account, user, case, document
    Base.metadata.create_all(bind=engine)


@app.get("/")
def read_root():
    """A simple root endpoint to confirm the API is running."""
    return {"message": "Welcome to Lexi-Graph!"}


@app.get("/health", tags=["Health Check"])
def health_check(db: Session = Depends(get_db)):
    """
    Performs a health check on the API and its connected services.
    Verifies connection to PostgreSQL and Redis.
    """
    status = {"api": "ok", "postgres": "error", "redis": "error"}

    # Check PostgreSQL connection
    try:
        db.execute(text("SELECT 1"))
        status["postgres"] = "ok"
    except Exception as e:
        print(f"PostgreSQL connection failed: {e}")
        # In a real app, you would log this error properly
        raise HTTPException(status_code=503, detail="Could not connect to the database.")

    # Check Redis connection
    try:
        r = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, decode_responses=True)
        r.ping()
        status["redis"] = "ok"
    except Exception as e:
        print(f"Redis connection failed: {e}")
        raise HTTPException(status_code=503, detail="Could not connect to Redis.")

    return status
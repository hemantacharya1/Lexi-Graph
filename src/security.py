from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
import models.user as user_model
import schemas.user as user_schemas 
from config import settings
from database import get_db

# --- Password Hashing Setup ---
# We use CryptContext to handle hashing. 'bcrypt' is the chosen algorithm.
# 'deprecated="auto"' means it will automatically handle upgrading hashes if we change algorithms later.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- JWT Configuration ---
# This is a secret key to sign our tokens. KEEP THIS SECRET.
# In a real app, load this from environment variables. For now, we'll add it to config.
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # 24 hours

# --- OAuth2 Scheme ---
# This tells FastAPI which URL to use to get the token.
# It's used by the interactive API docs (e.g., /docs) to handle login.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain password against a hashed one."""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Hashes a plain password."""
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Creates a new JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> user_model.User:
    """
    Dependency to get the current user from a JWT token.
    This is the core of our protection mechanism.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
        token_data = user_schemas.TokenData(email=email)
    except JWTError:
        raise credentials_exception

    user = db.query(user_model.User).filter(user_model.User.email == token_data.email).first()
    if user is None:
        raise credentials_exception
    return user
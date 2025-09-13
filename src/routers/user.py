from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import schemas.user as user_schema
import service.user as user_service
from database import get_db

router = APIRouter(
    prefix="/users",
    tags=["Users"],
)

@router.post("/signup", response_model=user_schema.User, status_code=status.HTTP_201_CREATED)
def signup(user: user_schema.UserCreate, db: Session = Depends(get_db)):
    """
    Handles user registration. Creates a new Account and a new User.
    """
    try:
        created_user = user_service.create_user(db, user=user)
        return created_user
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
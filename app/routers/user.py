from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import schemas, service
from ..database import get_db

router = APIRouter(
    prefix="/users",
    tags=["Users"],
)

@router.post("/signup", response_model=schemas.user.User, status_code=status.HTTP_201_CREATED)
def signup(user: schemas.user.UserCreate, db: Session = Depends(get_db)):
    """
    Handles user registration. Creates a new Account and a new User.
    """
    try:
        created_user = service.user.create_user(db, user=user)
        return created_user
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
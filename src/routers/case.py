from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID

import models.user as user_model
import schemas.case as case_schema
import service.case as case_service
from database import get_db
import security

router = APIRouter(
    prefix="/cases",
    tags=["Cases"],
    dependencies=[Depends(security.get_current_user)] # This protects all routes in this router
)

@router.post("/", response_model=case_schema.Case, status_code=status.HTTP_201_CREATED)
def create_case(
    case: case_schema.CaseCreate,
    db: Session = Depends(get_db),
    current_user: user_model.User = Depends(security.get_current_user)
):
    """Create a new case for the current user's account."""
    return case_service.create_case(db=db, case=case, account_id=current_user.account_id)

@router.get("/", response_model=list[case_schema.Case])
def read_cases(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: user_model.User = Depends(security.get_current_user)
):
    """Retrieve all cases for the current user's account."""
    cases = case_service.get_cases_by_account(db, account_id=current_user.account_id, skip=skip, limit=limit)
    return cases

@router.get("/{case_id}", response_model=case_schema.Case)
def read_case(
    case_id: UUID,
    db: Session = Depends(get_db),
    current_user: user_model.User = Depends(security.get_current_user)
):
    """Retrieve a specific case by its ID."""
    db_case = case_service.get_case(db, case_id=case_id, account_id=current_user.account_id)
    if db_case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return db_case
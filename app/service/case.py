from sqlalchemy.orm import Session
from uuid import UUID
import models.case as case_model
import schemas.case as case_schema

def create_case(db: Session, case: case_schema.CaseCreate, account_id: UUID) -> case_model.Case:
    """Creates a new case associated with an account."""
    db_case = case_model.Case(**case.model_dump(), account_id=account_id)
    db.add(db_case)
    db.commit()
    db.refresh(db_case)
    return db_case

def get_case(db: Session, case_id: UUID, account_id: UUID) -> case_model.Case | None:
    """Gets a specific case, ensuring it belongs to the correct account."""
    return db.query(case_model.Case).filter(
        case_model.Case.id == case_id,
        case_model.Case.account_id == account_id
    ).first()

def get_cases_by_account(db: Session, account_id: UUID, skip: int = 0, limit: int = 100) -> list[case_model.Case]:
    """Gets all cases associated with an account."""
    return db.query(case_model.Case).filter(case_model.Case.account_id == account_id).offset(skip).limit(limit).all()
from sqlalchemy.orm import Session
from uuid import UUID
from .. import models, schemas

def create_case(db: Session, case: schemas.case.CaseCreate, account_id: UUID) -> models.case.Case:
    """Creates a new case associated with an account."""
    db_case = models.case.Case(**case.model_dump(), account_id=account_id)
    db.add(db_case)
    db.commit()
    db.refresh(db_case)
    return db_case

def get_case(db: Session, case_id: UUID, account_id: UUID) -> models.case.Case | None:
    """Gets a specific case, ensuring it belongs to the correct account."""
    return db.query(models.case.Case).filter(
        models.case.Case.id == case_id,
        models.case.Case.account_id == account_id
    ).first()

def get_cases_by_account(db: Session, account_id: UUID, skip: int = 0, limit: int = 100) -> list[models.case.Case]:
    """Gets all cases associated with an account."""
    return db.query(models.case.Case).filter(models.case.Case.account_id == account_id).offset(skip).limit(limit).all()
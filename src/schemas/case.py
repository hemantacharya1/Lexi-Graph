from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

class CaseBase(BaseModel):
    name: str
    description: str | None = None

class CaseCreate(CaseBase):
    pass

class Case(CaseBase):
    id: UUID
    account_id: UUID
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True
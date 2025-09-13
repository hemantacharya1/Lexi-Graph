from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

class DocumentBase(BaseModel):
    file_name: str

class DocumentCreate(DocumentBase):
    pass

class Document(DocumentBase):
    id: UUID
    case_id: UUID
    status: str
    status_message: str | None = None
    created_at: datetime
    processed_at: datetime | None = None

    class Config:
        from_attributes = True
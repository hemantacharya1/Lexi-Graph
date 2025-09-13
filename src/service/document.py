import os
import shutil
from fastapi import UploadFile
from sqlalchemy.orm import Session
import models.document as document_model
import models.case as case_model
import schemas.document as document_schema
from config import settings
import uuid
from uuid import UUID


def create_document_record(db: Session, case_id: UUID, user_id: UUID, file: UploadFile) -> document_model.Document:
    """
    Creates a document record in the database and saves the file to storage.
    """
    # 1. Create a unique path for the document
    document_id = uuid.uuid4()
    case_storage_path = os.path.join(settings.STORAGE_PATH, str(case_id))
    os.makedirs(case_storage_path, exist_ok=True)
    
    # Use the document's own UUID as its filename to guarantee uniqueness
    file_extension = os.path.splitext(file.filename)[1]
    unique_filename = f"{document_id}{file_extension}"
    file_path = os.path.join(case_storage_path, unique_filename)

    # 2. Save the file to the persistent volume
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # 3. Create the database record
    db_document = document_model.Document(
        id=document_id,
        file_name=file.filename,
        file_path=file_path,
        file_type=file.content_type,
        case_id=case_id,
        uploaded_by_id=user_id,
        status="PENDING"
    )
    db.add(db_document)
    db.commit()
    db.refresh(db_document)
    
    return db_document
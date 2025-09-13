from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID
import models.user as user_model
import schemas.document as document_schema
import service.document as document_service
import service.case as case_service
from database import get_db
import security
from tasks import prepare_and_process_document

router = APIRouter(
    prefix="/documents",
    tags=["Documents"],
    dependencies=[Depends(security.get_current_user)]
)

@router.post("/cases/{case_id}", response_model=document_schema.Document, status_code=status.HTTP_202_ACCEPTED)
def upload_document_to_case(
    case_id: UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: user_model.User = Depends(security.get_current_user)
):
    """
    Uploads a document to a specific case, saves it, creates a DB record,
    and dispatches a background task to process it.
    """
    # 1. Verify the user has access to this case
    db_case = case_service.get_case(db, case_id=case_id, account_id=current_user.account_id)
    if db_case is None:
        raise HTTPException(status_code=404, detail="Case not found or access denied.")

    # 2. Create DB record and save the file
    try:
        db_document = document_service.create_document_record(
            db=db, case_id=case_id, user_id=current_user.id, file=file
        )
    finally:
        file.file.close() # Ensure the file is closed

    # 3. Dispatch the background processing task
    prepare_and_process_document.delay(str(db_document.id))

    return db_document
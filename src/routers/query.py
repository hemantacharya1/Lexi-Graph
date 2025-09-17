from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID

import models.user as user_model
import schemas.query as query_schema
import service.case as case_service
import service.query_service as query_service
from database import get_db
import security

router = APIRouter(
    prefix="/cases/{case_id}/query", # The prefix is more specific now
    tags=["Query"],
    dependencies=[Depends(security.get_current_user)] # Protect all routes in this router
)

@router.post("/", response_model=query_schema.QueryResponse)
def query_case(
    case_id: UUID,
    request: query_schema.QueryRequest,
    db: Session = Depends(get_db),
    current_user: user_model.User = Depends(security.get_current_user)
):
    """
    Accepts a user's question about a specific case and returns a synthesized
    answer based on the documents indexed for that case.
    """
    # 1. Authorization: Verify the user has access to this case.
    # This is a critical security check.
    db_case = case_service.get_case(db, case_id=case_id, account_id=current_user.account_id)
    if db_case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found or you do not have permission to access it."
        )

    # 2. Delegation: Pass the actual query processing to our dedicated service.
    # The router's job is to handle the web layer, not the business logic.
    try:
        response = query_service.process_query(case_id=str(case_id), query=request.query)
        return response
    except Exception as e:
        # This is a general catch-all for unexpected errors in the RAG pipeline.
        print(f"An unexpected error occurred during query processing: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while processing your query."
        )
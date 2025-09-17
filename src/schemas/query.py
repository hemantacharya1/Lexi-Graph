from pydantic import BaseModel
from uuid import UUID

class QueryRequest(BaseModel):
    """
    The request model for asking a question to a case.
    """
    query: str


class SourceDocument(BaseModel):
    """
    Represents a single source document used to generate the answer.
    This provides the necessary citation and evidence.
    """
    document_id: UUID
    file_name: str
    page_number: str
    absolute_text: str


class QueryResponse(BaseModel):
    """
    The response model containing the synthesized answer and its sources.
    """
    answer: str
    sources: list[SourceDocument]
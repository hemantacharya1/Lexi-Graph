from database import Base
from sqlalchemy import UUID, Column, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

class Document(Base):
    __tablename__ = "documents"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String(255), nullable=False)
    storage_path = Column(String(1024), nullable=False) 
    file_type = Column(String(50), nullable=True) # e.g., "pdf", "docx"
    status = Column(String(50), nullable=False, default='PENDING', index=True) # PENDING, PROCESSING, COMPLETED, FAILED
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    processed_at = Column(DateTime(timezone=True), nullable=True)

    # --- Foreign Keys ---
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False)
    uploaded_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # --- Relationships ---
    # Many Documents belong to one Case
    case = relationship("Case", back_populates="documents")
    # Many Documents can be uploaded by one User
    uploaded_by = relationship("User", back_populates="documents")
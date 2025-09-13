from database import Base
from sqlalchemy import UUID, Column, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

class Document(Base):
    __tablename__ = "documents"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # --- CHANGE 'filename' to 'file_name' for consistency ---
    file_name = Column(String(255), nullable=False)
    
    # --- CHANGE 'storage_path' to 'file_path' ---
    # This will store the path INSIDE the container, e.g., /storage/case_id/doc_id.pdf
    file_path = Column(String(1024), nullable=False, unique=True) 
    
    file_type = Column(String(50), nullable=True) # e.g., "application/pdf"
    
    # --- UPDATED STATUSES to be more explicit ---
    status = Column(
        String(50), 
        nullable=False, 
        default='PENDING', 
        index=True
    ) # PENDING, PROCESSING, COMPLETED, FAILED
    
    status_message = Column(Text, nullable=True) # To store error messages

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    processed_at = Column(DateTime(timezone=True), nullable=True)

    # --- Foreign Keys ---
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False)
    uploaded_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # --- Relationships ---
    case = relationship("Case", back_populates="documents")
    uploaded_by = relationship("User", back_populates="documents")
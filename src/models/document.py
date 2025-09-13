from database import Base
from sqlalchemy import UUID, Column, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

class LegalDocument(Base):
    __tablename__ = "documents"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_name = Column(String(255), nullable=False)
    file_path = Column(String(1024), nullable=False, unique=True) 
    file_type = Column(String(50), nullable=True)
    status = Column(String(50), nullable=False, default='PENDING', index=True)
    status_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    processed_at = Column(DateTime(timezone=True), nullable=True)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False)
    uploaded_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # --- Relationships (UPDATED) ---
    case = relationship("LegalCase", back_populates="documents")
    uploaded_by = relationship("User", back_populates="documents")
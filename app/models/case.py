from database import Base
from sqlalchemy import UUID, Column, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

class Case(Base):
    __tablename__ = "cases"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    # --- Foreign Keys ---
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    # --- Relationships ---
    # Many Cases belong to one Account
    account = relationship("Account", back_populates="cases")
    # One Case has many Documents
    documents = relationship("Document", back_populates="case", cascade="all, delete-orphan")
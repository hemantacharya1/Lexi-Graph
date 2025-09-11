from database import Base
from sqlalchemy import UUID, Column, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # --- Foreign Keys ---
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    # --- Relationships ---
    # Many Users belong to one Account
    account = relationship("Account", back_populates="users")
    # One User can upload many Documents
    documents = relationship("Document", back_populates="uploaded_by")
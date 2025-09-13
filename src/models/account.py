from database import Base
from sqlalchemy import UUID, Column, String, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

class Account(Base):
    __tablename__ = "accounts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    # --- Relationships ---
    # One Account has many Users
    users = relationship("User", back_populates="account", cascade="all, delete-orphan")
    # One Account has many Cases
    cases = relationship("Case", back_populates="account", cascade="all, delete-orphan")
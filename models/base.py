"""SQLAlchemy models for BharatBot database."""
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Integer, ForeignKey, CheckConstraint, Text, Boolean, func, literal
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    user_id = Column(String(32), primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True, index=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp(), default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=datetime.utcnow, default=datetime.utcnow)
    is_active = Column(Boolean, nullable=False, server_default=literal(True), default=True)

    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    jti = Column(String(255), primary_key=True)
    user_id = Column(String(32), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, nullable=False, server_default=literal(False), default=False)
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp(), default=datetime.utcnow)

    user = relationship("User", back_populates="refresh_tokens")


class Session(Base):
    __tablename__ = "sessions"

    session_id = Column(String(32), primary_key=True)
    user_id = Column(String(32), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp(), default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=datetime.utcnow, default=datetime.utcnow)
    title = Column(String)
    lang = Column(String, nullable=False, server_default="en", default="en")
    is_active = Column(Boolean, nullable=False, server_default=literal(True), default=True)

    __table_args__ = (
        CheckConstraint("lang IN ('en', 'hi', 'ta', 'te', 'mr', 'gu', 'kn', 'ml', 'pa', 'bn')"),
    )

    user = relationship("User", back_populates="sessions")
    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    message_id = Column(String(32), primary_key=True)
    session_id = Column(String(32), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(10), nullable=False)
    content_type = Column(String(10), nullable=False)
    original_text = Column(Text)
    english_text = Column(Text)
    response_text = Column(Text)
    detected_lang = Column(String(10))
    audio_s3_uri = Column(String)
    has_audio_out = Column(Boolean, nullable=False, server_default=literal(False), default=False)
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp(), default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')"),
        CheckConstraint("content_type IN ('text', 'voice')"),
    )

    session = relationship("Session", back_populates="messages")

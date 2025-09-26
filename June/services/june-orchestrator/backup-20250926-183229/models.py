# June/services/june-orchestrator/models.py
# Database models for conversation management

from datetime import datetime
from typing import Optional, Dict, Any, List
import uuid
from sqlalchemy import create_engine, Column, String, Text, Integer, Float, DateTime, Boolean, JSON, ForeignKey, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import sessionmaker, relationship
import os

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    keycloak_id = Column(String(255), unique=True, nullable=False)
    username = Column(String(255), nullable=False)
    email = Column(String(255))
    display_name = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_active = Column(DateTime, default=datetime.utcnow)
    preferences = Column(JSON, default={})
    metadata = Column(JSON, default={})
    
    conversations = relationship("Conversation", back_populates="user")
    messages = relationship("Message", back_populates="user")

class Conversation(Base):
    __tablename__ = 'conversations'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    title = Column(String(255))
    status = Column(String(50), default='active')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    ended_at = Column(DateTime)
    message_count = Column(Integer, default=0)
    total_duration = Column(Integer, default=0)
    quality_score = Column(Float)
    tags = Column(ARRAY(String))
    metadata = Column(JSON, default={})
    summary = Column(Text)
    
    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_conversations_user_id', 'user_id'),
        Index('idx_conversations_created_at', 'created_at'),
        Index('idx_conversations_status', 'status'),
    )

class Message(Base):
    __tablename__ = 'messages'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    role = Column(String(20), nullable=False)  # user, assistant, system, tool
    content = Column(Text, nullable=False)
    audio_metadata = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow)
    sequence_number = Column(Integer, nullable=False)
    processing_time = Column(Integer)
    tokens_used = Column(Integer)
    model_used = Column(String(100))
    confidence_score = Column(Float)
    metadata = Column(JSON, default={})
    
    conversation = relationship("Conversation", back_populates="messages")
    user = relationship("User", back_populates="messages")
    
    __table_args__ = (
        Index('idx_messages_conversation_id', 'conversation_id'),
        Index('idx_messages_created_at', 'created_at'),
        Index('idx_messages_role', 'role'),
    )

class Tool(Base):
    __tablename__ = 'tools'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), unique=True, nullable=False)
    display_name = Column(String(255), nullable=False)
    description = Column(Text)
    category = Column(String(100))
    version = Column(String(20), default='1.0.0')
    enabled = Column(Boolean, default=True)
    config = Column(JSON, default={})
    schema = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class StreamingSession(Base):
    __tablename__ = 'streaming_sessions'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey('conversations.id', ondelete='CASCADE'))
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    session_token = Column(String(255), nullable=False)
    status = Column(String(20), default='active')
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime)
    duration = Column(Integer)
    bytes_transmitted = Column(Integer, default=0)
    error_message = Column(Text)
    client_info = Column(JSON, default={})

# Database connection setup
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:june_db_pass_2024@postgresql:5432/june_db")
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_tables():
    """Create all tables"""
    Base.metadata.create_all(bind=engine)
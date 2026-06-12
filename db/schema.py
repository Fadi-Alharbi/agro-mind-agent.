import os
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, Text, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker

DB_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DB_DIR, "agromind.db")

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
Base = declarative_base()

class Customer(Base):
    """Long-term memory: Customers"""
    __tablename__ = 'customers'
    id = Column(String, primary_key=True)  # E.g., customer_id or phone
    profile_data = Column(Text, default="{}") # JSON string for location, preferences
    created_at = Column(DateTime, default=datetime.utcnow)

class Conversation(Base):
    """Long-term memory: Conversations/Sessions"""
    __tablename__ = 'conversations'
    id = Column(String, primary_key=True)  # session_id
    customer_id = Column(String, ForeignKey('customers.id'))
    chat_history = Column(Text, default="[]") # JSON string array of turns
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Diagnosis(Base):
    """Long-term memory: Specific diagnosis events"""
    __tablename__ = 'diagnoses'
    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String, ForeignKey('conversations.id'))
    crop_type = Column(String, nullable=True)
    disease_name = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    recommended_product_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

def init_db():
    print(f"Initializing database at {DB_PATH}")
    Base.metadata.create_all(engine)
    print("Tables created successfully.")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

if __name__ == "__main__":
    init_db()

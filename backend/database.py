import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from models import Base

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'subscriptions.db')
DATABASE_URI = os.environ.get('DATABASE_URL', f'sqlite:///{DB_PATH}')

engine = create_engine(DATABASE_URI, connect_args={"check_same_thread": False})
SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

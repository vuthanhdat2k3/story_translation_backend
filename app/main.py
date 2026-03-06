"""Story Translation API - FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db.database import engine, Base
from app.api import novel, chapter, translate, character_map

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create database tables on startup."""
    try:
        Base.metadata.create_all(bind=engine)
        logging.info("Database tables created / verified")
    except Exception as e:
        logging.error(f"Database startup error (non-fatal): {e}")
    yield


app = FastAPI(
    title="Story Translation API",
    description="AI-powered Chinese to Vietnamese novel translation service using Google Gemini",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(novel.router)
app.include_router(chapter.router)
app.include_router(translate.router)
app.include_router(character_map.router)


@app.get("/")
def root():
    return {
        "app": "Story Translation API",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}

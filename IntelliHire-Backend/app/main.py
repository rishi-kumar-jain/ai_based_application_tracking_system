from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.db import seed_roles
from mangum import Mangum
from app.core.config import get_settings
from app.core.logger import get_logger
from app.core.exceptions import register_exception_handlers
from app.db.session import build_engine_and_sessionmaker, ensure_schema
from app.db.base import Base
from app.routes.health import router as health_router
from app.routes.job_descriptions import router as jd_router
from app.routes.screening import router as screening_router
from app.routes.pipeline import router as pipeline_router
from app.routes.assessments import router as assessments_router
from app.routes.panel import router as panel_router
from app.routes.auth import router as auth_router


settings = get_settings()
logger = get_logger("main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.parser_service import verify_tesseract
    verify_tesseract()  # runs once at startup, not at import time
    logger.info("Starting IntelliHire API in env=%s", settings.app_env)

    engine, session_maker = build_engine_and_sessionmaker(settings)
    app.state.engine = engine
    app.state.session_maker = session_maker

    ensure_schema(engine, settings.db_schema)

    # if settings.init_db_on_startup:
    #     logger.info("INIT_DB_ON_STARTUP=true, creating any missing tables")
    #     Base.metadata.create_all(bind=engine)

    yield

    engine.dispose()
    logger.info("Shutting down IntelliHire API")

app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    docs_url=settings.docs_url,
    openapi_url=settings.openapi_url,
    redoc_url=settings.redoc_url,
)



app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
       

    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


register_exception_handlers(app)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info("Request started method=%s path=%s", request.method, request.url.path)
    response = await call_next(request)
    logger.info("Request completed method=%s path=%s status=%s", request.method, request.url.path, response.status_code)
    return response

app.include_router(health_router)
app.include_router(jd_router)
app.include_router(screening_router)
app.include_router(pipeline_router)
app.include_router(assessments_router)
app.include_router(panel_router)
app.include_router(auth_router)



handler = Mangum(app)







@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # response.headers["X-XSS-Protection"] = "1; mode=block"
    return response






"""for cleansing of data use this sequence  order 
TRUNCATE TABLE
    intellihire.application_stage_history,
    intellihire.assessments,
    intellihire.panel_assignments,
    intellihire.applications,
    intellihire.screening_results,
    intellihire.resumes,
    intellihire.job_descriptions
RESTART IDENTITY CASCADE;
"""

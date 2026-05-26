"""FastAPI приложение Admin API. Запуск: uvicorn api.main:app --host 0.0.0.0 --port 8092."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.backend.routers.admin import router as admin_router
from services.backend.routers import webhooks


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    try:
        from shared.db.session import close_engine
        await close_engine()
    except Exception:
        pass


app = FastAPI(title="NeuroBox Admin API", version="1.0", lifespan=lifespan)

origins = []
try:
    from shared.config import settings
    raw = (getattr(settings, "admin_cors_origins", None) or "").strip()
    if raw:
        origins = [x.strip() for x in raw.split(",") if x.strip()]
except Exception:
    pass
if not origins:
    origins = []

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin_router, prefix="/api/v1/admin", tags=["admin"])
app.include_router(webhooks.router)


@app.get("/health")
async def health():
    return {"ok": True}

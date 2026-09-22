import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .agent_routes import router as agent_router
from .auth_routes import router
from .config import Settings
from .context_routes import router as context_router
from .database import Database
from .document_routes import router as document_router
from .folder_routes import router as folder_router
from .job_routes import router as job_router
from .memory_routes import router as memory_router
from .namespace_routes import router as namespace_router
from .session_routes import router as session_router
from .space_routes import router as space_router


def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    app = FastAPI(title="Knowledge Context Studio", version="1.0.0-dev")
    app.state.settings = settings
    app.state.database = Database(settings.database_url, testing=settings.testing)

    @app.middleware("http")
    async def request_boundary(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin and origin != settings.public_origin:
            return JSONResponse({"detail": "不允許此來源"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(IntegrityError)
    async def conflict(request: Request, exc: IntegrityError):
        return JSONResponse(
            {"detail": "資料已變更或發生重複，請重新載入", "request_id": request.state.request_id},
            status_code=409,
        )

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready():
        with app.state.database.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok"}

    app.include_router(router)
    app.include_router(agent_router)
    app.include_router(space_router)
    app.include_router(session_router)
    app.include_router(job_router)
    app.include_router(memory_router)
    app.include_router(context_router)
    app.include_router(document_router)
    app.include_router(folder_router)
    app.include_router(namespace_router)
    if (settings.frontend_dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=settings.frontend_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path.split("/")[0] in ("v1", "health", "assets", "docs", "redoc", "openapi.json"):
            raise HTTPException(404, "找不到接口")
        index = settings.frontend_dist / "index.html"
        if not index.is_file():
            raise HTTPException(503, "前端尚未建置")
        return FileResponse(index)

    return app

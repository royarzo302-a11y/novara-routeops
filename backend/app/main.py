import hmac
import os
from contextlib import asynccontextmanager
from threading import Lock

from fastapi import Depends, FastAPI
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from app.api.geospatial import bearer
from app.api.geospatial import router as geospatial_router
from app.api.ingestion import router as ingestion_router
from app.api.joint_planning import router as joint_planning_router
from app.api.operator import router as operator_router
from app.api.routes import router
from app.database import database, initialize
from app.geo.service import GeoSettings
from app.optimization.travel import TravelTimeProvider


def create_app(
    database_url: str | None = None,
    *,
    joint_travel_provider: TravelTimeProvider | None = None,
    joint_allow_simulation: bool = False,
    geo_settings: GeoSettings | None = None,
) -> FastAPI:
    engine, sessions = database(
        database_url or os.getenv("DATABASE_URL", "sqlite:///./routeops.db")
    )

    @asynccontextmanager
    async def lifespan(app):
        initialize(engine)
        yield
        engine.dispose()

    app = FastAPI(
        title="Novara RouteOps",
        version="0.4.0",
        lifespan=lifespan,
        description="Planificación supervisada v0.4. Horas locales de Santiago.",
    )
    app.state.sessions = sessions
    # The MVP runs one worker; serialize database workflows and resource reservations.
    app.state.database_lock = Lock()
    app.include_router(router)
    app.include_router(ingestion_router, dependencies=[Depends(bearer)])
    app.include_router(joint_planning_router, dependencies=[Depends(bearer)])
    app.include_router(geospatial_router)
    app.include_router(operator_router)
    app.state.geo_settings = geo_settings if geo_settings is not None else GeoSettings.from_env()

    app.state.joint_travel_provider = joint_travel_provider
    app.state.joint_allow_simulation = joint_allow_simulation

    @app.middleware("http")
    async def protect_private_paths(request, call_next):
        path = request.url.path.removeprefix(request.scope.get("root_path", ""))
        private = path.startswith(("/v2/", "/v3/", "/v4/", "/v5/"))
        token = app.state.geo_settings.token
        if (
            private
            and token
            and not hmac.compare_digest(
                request.headers.get("authorization", "").encode(), f"Bearer {token}".encode()
            )
        ):
            return JSONResponse(
                status_code=401,
                content={"detail": "Autorización requerida"},
                headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
            )
        response = await call_next(request)
        if private:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def private_validation_error(request, exc):
        if request.url.path.removeprefix(request.scope.get("root_path", "")).startswith(
            ("/v2/", "/v3/", "/v4/", "/v5/")
        ):
            # FastAPI's default includes rejected input; these APIs must not echo private values.
            return JSONResponse(
                status_code=422, content={"detail": "Datos de solicitud no válidos"}
            )
        return await request_validation_exception_handler(request, exc)

    @app.exception_handler(ResponseValidationError)
    async def private_response_error(request, exc):
        if request.url.path.removeprefix(request.scope.get("root_path", "")).startswith(
            ("/v2/", "/v3/", "/v4/", "/v5/")
        ):
            return JSONResponse(status_code=500, content={"detail": "Respuesta no disponible"})
        raise exc

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST", "PUT", "PATCH"],
        allow_headers=["Authorization", "Content-Type"],
    )
    return app


app = create_app()

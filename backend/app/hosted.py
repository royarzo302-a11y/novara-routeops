"""Single-origin, isolated demo for Render. Contains no operational data sources."""

import hashlib
import hmac
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from time import monotonic
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from openpyxl import Workbook
from pydantic import BaseModel, Field
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.database import database, initialize
from app.geo.providers import SyntheticGeocodingProvider
from app.geo.service import GeoSettings
from app.main import create_app
from app.models.ingestion import CustomerCode
from scripts.demo_data import STOPS, TERMINALS, demo_points, road_demo, seed_resources

COOKIE = "novara_demo"
SESSION_SECONDS = 2 * 60 * 60
MAX_SESSIONS = 8
MAX_BODY = 512 * 1024
MEDIA_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
GET_ROUTES = re.compile(
    r"/(?:v2/(?:customers|terminals|ingestions(?:/[0-9a-f-]{36})?)"
    r"|v4/(?:geo/(?:session|matrix-catalog|matrices/[0-9a-f-]{36}/origins"
    r"|requests/[0-9a-f-]{36}/location))|v5/operator/preparation|depots|vehicles|drivers)"
)
POST_ROUTES = {
    "/v3/plans/preview",
    "/v4/geo/matrices",
    "/v5/operator/ingestions/automatic",
    "/v5/operator/locations/prepare",
    "/v5/operator/plans/export",
}
SPA_PAGES = {
    "",
    "inicio",
    "preparacion",
    "importar",
    "solicitudes",
    "ubicaciones",
    "flota",
    "planificacion",
}
SAMPLES = {
    "gran-america": (CustomerCode.GRAN_AMERICA, (10, 12, 13, 14, 15, 16, 4, 6)),
    "lo-blanco": (CustomerCode.LO_BLANCO, (11, 18, 9, 14, 19, 20, 21, 1)),
}
VALID_COMMUNES = {address: commune for _, address, commune, *_ in STOPS}


@dataclass
class DemoSession:
    engine: Engine
    sessions: sessionmaker
    date: datetime
    expires: float
    rosters: dict[str, None] = field(default_factory=dict)
    uploads: int = 0
    matrices: int = 0
    latest_plan: dict | None = None

    @property
    def valid_communes(self):
        return VALID_COMMUNES


class PasswordInput(BaseModel):
    password: str = Field(max_length=256)


def workbook(customer, stops, day, *, has_errors):
    book = Workbook()
    sheet = book.active
    sheet.title = "Acercamiento"
    labels = ["Fecha", "Hora Inicio", "Código", "Nombres", "Dirección", "Comuna", "Teléfono"]
    lo_blanco = customer == CustomerCode.LO_BLANCO
    if lo_blanco:
        labels[:2] = ["Fecha de presentación", "Hora de ingreso"]
        labels.append("Depósito asignado")
    sheet.append(labels)
    for index, stop in enumerate(stops, 1):
        _, address, commune, *_ = STOPS[stop]
        hour = ("04:25", "06:10") if lo_blanco else ("04:10", "06:00")
        row = [
            day.date(),
            hour[index > 4],
            f"NOVARA-DEMO-{customer}-{index:02}",
            f"Persona ficticia {index:02}",
            address,
            None if has_errors and index == 1 else commune,
            f"9700000{index:02}",
        ]
        sheet.append(row + ([TERMINALS[customer][0]] if lo_blanco else []))
        if has_errors and index == 4:
            sheet.append([None] * len(labels))
            sheet.append(labels)
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def create_hosted_app(password: str, web: Path, *, secure_cookie: bool = True):
    if len(password.encode()) < 32 or len(password) > 256:
        raise RuntimeError("Configura NOVARA_DEMO_PASSWORD con 32–256 caracteres seguros.")
    index = web / "index.html"
    if not index.is_file() or not (web / "assets").is_dir():
        raise RuntimeError("El frontend compilado no está disponible.")
    secret = secrets.token_urlsafe(32)
    backend = create_app(
        "sqlite:///:memory:",
        geo_settings=GeoSettings(
            token=secret,
            geocoder=SyntheticGeocodingProvider(demo_points),
            road=road_demo(),
            allow_simulation=True,
            demo_mode=True,
        ),
    )
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    sessions: dict[str, DemoSession] = {}

    def error(status, detail):
        return JSONResponse(
            {"detail": detail}, status_code=status, headers={"Cache-Control": "no-store"}
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, _exc):
        return error(422, "Datos de solicitud no válidos")

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        method = request.method
        if method in {"POST", "PATCH"}:
            if request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
                return error(403, "Solicitudes válidas únicamente desde la demo.")
            if request.headers.get("transfer-encoding"):
                return error(411, "Se requiere un tamaño de solicitud explícito.")
            length = request.headers.get("content-length", "")
            if not length.isascii() or not length.isdecimal() or len(length) > 8:
                return error(411, "Se requiere un tamaño de solicitud explícito.")
            if int(length) > MAX_BODY:
                return error(413, "La solicitud supera el límite de 512 KiB.")
        if path != "/api/demo/login":
            current = sessions.get(request.cookies.get(COOKIE, ""))
            if current is None or current.expires <= monotonic():
                return error(401, "Ingresa la clave de la demo para continuar.")
            request.state.hosted_session = current
            if not path.startswith("/api/demo/"):
                inner = path.removeprefix("/api")
                allowed = (
                    (method == "GET" and GET_ROUTES.fullmatch(inner))
                    or (method == "POST" and inner in POST_ROUTES)
                    or (method == "PATCH" and re.fullmatch(r"/v2/requests/[0-9a-f-]{36}", inner))
                )
                if not allowed:
                    return error(404, "Ruta no disponible en la demo.")
                request.scope["headers"] = [
                    (name, value)
                    for name, value in request.scope["headers"]
                    if name != b"authorization"
                ] + [(b"authorization", f"Bearer {secret}".encode())]
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    def open_session(response: Response):
        with backend.state.database_lock:
            now = monotonic()
            for key in [k for k, value in sessions.items() if value.expires <= now]:
                sessions.pop(key).engine.dispose()
            if len(sessions) >= MAX_SESSIONS:
                raise HTTPException(429, "La demo está llena. Reintenta más tarde.")
            engine, factory = database("sqlite:///:memory:")
            initialize(engine)
            with factory() as db:
                seed_resources(db)
            key = secrets.token_urlsafe(32)
            day = datetime.now(ZoneInfo("America/Santiago")) + timedelta(days=1)
            sessions[key] = DemoSession(engine, factory, day, now + SESSION_SECONDS)
            response.set_cookie(
                COOKIE,
                key,
                max_age=SESSION_SECONDS,
                httponly=True,
                secure=secure_cookie,
                samesite="strict",
                path="/",
            )
        return {"authenticated": True}

    @app.post("/api/demo/login")
    def login(body: PasswordInput, request: Request, response: Response):
        if not hmac.compare_digest(body.password.encode(), password.encode()):
            raise HTTPException(401, "Clave de demo incorrecta.")
        current = sessions.get(request.cookies.get(COOKIE, ""))
        if current and current.expires > monotonic():
            return {"authenticated": True}
        return open_session(response)

    def remove_session(request: Request):
        with backend.state.database_lock:
            previous = sessions.pop(request.cookies.get(COOKIE, ""), None)
            if previous:
                previous.engine.dispose()

    @app.post("/api/demo/logout")
    def logout(request: Request, response: Response):
        remove_session(request)
        response.delete_cookie(
            COOKIE, path="/", httponly=True, secure=secure_cookie, samesite="strict"
        )
        return {"authenticated": False}

    @app.post("/api/demo/reset")
    def reset(request: Request, response: Response):
        remove_session(request)
        return open_session(response)

    @app.get("/api/demo/rosters/{slug}")
    def roster(slug: str, request: Request):
        if slug == "rapida":
            slug = secrets.choice(list(SAMPLES))
            customer, stops = SAMPLES[slug]
            stops = list(stops)
            secrets.SystemRandom().shuffle(stops)
            has_errors = False
        elif slug in SAMPLES:
            customer, stops = SAMPLES[slug]
            has_errors = True
        else:
            raise HTTPException(404, "Nómina de ejemplo inexistente.")
        current = request.state.hosted_session
        data = workbook(customer, stops, current.date, has_errors=has_errors)
        with backend.state.database_lock:
            current.rosters[hashlib.sha256(data).hexdigest()] = None
            if len(current.rosters) > 20:
                del current.rosters[next(iter(current.rosters))]
        return Response(
            data,
            media_type=MEDIA_XLSX,
            headers={
                "Content-Disposition": f'attachment; filename="demo-{slug}.xlsx"',
            },
        )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    app.mount("/api", backend)
    app.mount("/assets", StaticFiles(directory=web / "assets"))

    @app.get("/{path:path}")
    def home(path: str):
        if path not in SPA_PAGES:
            raise HTTPException(404)
        return FileResponse(
            index,
            headers={
                "Cache-Control": "no-cache",
                "Content-Security-Policy": (
                    "default-src 'self'; img-src 'self' data: blob:; "
                    "style-src 'self' 'unsafe-inline'; "
                    "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
                ),
            },
        )

    return app


def application():
    return create_hosted_app(
        os.getenv("NOVARA_DEMO_PASSWORD", ""),
        Path(os.getenv("NOVARA_WEB_ROOT", "frontend/dist")),
        secure_cookie=os.getenv("RENDER") == "true" or os.getenv("NOVARA_DEMO_HTTP") != "1",
    )

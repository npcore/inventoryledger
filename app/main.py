import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from . import db, services
from .ledger import totals
from .models import Item, User
from .routes import auth, entries, items, periods
from .services import BusinessError
from .web import LoginRequired, current_user, flash, get_db, redirect, render


def _secret_key() -> str:
    if key := os.environ.get("INVENTORY_SECRET"):
        return key
    path = db.DATA_DIR / "secret.key"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32))
        path.chmod(0o600)
    return path.read_text().strip()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    with db.SessionLocal() as s:
        services.ensure_locations(s)
        s.commit()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="재고수불 관리", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.add_middleware(SessionMiddleware, secret_key=_secret_key(), max_age=60 * 60 * 12, same_site="lax")
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
    for r in (auth.router, items.router, entries.router, periods.router):
        app.include_router(r)

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if request.url.scheme == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, exc: LoginRequired):
        return redirect("/login")

    @app.exception_handler(BusinessError)
    async def _business_error(request: Request, exc: BusinessError):
        flash(request, str(exc), "error")
        return redirect(request.headers.get("referer") or "/")

    @app.get("/")
    def dashboard(request: Request, user: User = Depends(current_user), s: Session = Depends(get_db)):
        p = services.current_period(s)
        rows = services.ledger_rows(s, p) if p else []
        return render(request, "dashboard.html", user=user, period=p, rows=rows, t=totals(rows),
                      item_count=s.scalar(select(func.count(Item.code)).where(Item.active.is_(True))),
                      locked=services.locked_until(s))

    return app


app = create_app()

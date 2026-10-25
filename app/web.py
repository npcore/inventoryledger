"""라우트 공용 도우미: DB 세션, 로그인 사용자, 템플릿 렌더링, 알림 메시지."""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import db
from .models import Item, Period, User
from .services import BusinessError, current_period, ensure_locations, periods

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def _num(v) -> str:
    if v is None or v == "":
        return ""
    return f"{Decimal(v):,.0f}"


def _unit(v) -> str:
    if v is None or v == "":
        return ""
    return f"{Decimal(v):,.2f}"


templates.env.filters["n"] = _num
templates.env.filters["unit"] = _unit


class LoginRequired(Exception):
    pass


def get_db() -> Iterator[Session]:
    with db.SessionLocal() as s:
        yield s


def current_user(request: Request, s: Session = Depends(get_db)) -> User:
    uid = request.session.get("uid")
    user = s.get(User, uid) if uid else None
    if user is None or not user.active:
        raise LoginRequired
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "관리자만 사용할 수 있습니다.")
    return user


def flash(request: Request, message: str, kind: str = "ok") -> None:
    request.session["flash"] = request.session.get("flash", []) + [{"kind": kind, "message": message}]


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def render(request: Request, template: str, **ctx):
    ctx.setdefault("user", None)
    ctx["flashes"] = request.session.pop("flash", [])
    ctx["today"] = date.today()
    return templates.TemplateResponse(request, template, ctx)


def resolve_period(s: Session, period_id: int | None) -> Period:
    p = s.get(Period, period_id) if period_id else current_period(s)
    if p is None:
        raise BusinessError("결산 기간이 없습니다. [결산 기간] 메뉴에서 기존 엑셀 결산 파일을 먼저 가져오세요.")
    return p


def entry_context(s: Session, p: Period) -> dict:
    """입고·대체·이동 화면 공통 데이터."""
    return {
        "period": p,
        "periods": periods(s),
        "locations": ensure_locations(s),
        "items": s.scalars(select(Item).where(Item.active.is_(True)).order_by(Item.code)).all(),
    }


def parse_date(v: str) -> date:
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise BusinessError(f"날짜 형식이 올바르지 않습니다: {v}")


def require_item(s: Session, code: str) -> Item:
    code = code.split()[0].strip() if code.strip() else ""
    item = s.get(Item, code)
    if item is None:
        raise BusinessError(f"등록되지 않은 품목코드입니다: {code or '(빈 값)'}")
    return item

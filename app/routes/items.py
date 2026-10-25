from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..importers import is_item_code
from ..models import Item, User
from ..services import BusinessError
from ..web import current_user, flash, get_db, redirect, render

router = APIRouter()


@router.get("/items")
def items(request: Request, q: str = "", show: str = "active", user: User = Depends(current_user),
          s: Session = Depends(get_db)):
    stmt = select(Item).order_by(Item.code)
    if show != "all":
        stmt = stmt.where(Item.active.is_(True))
    if q:
        stmt = stmt.where(or_(Item.code.contains(q), Item.name.contains(q)))
    codes = s.scalars(select(Item.code).order_by(Item.code.desc())).all()
    next_code = _next_code(codes)
    return render(request, "items.html", user=user, items=s.scalars(stmt).all(), q=q, show=show, next_code=next_code)


def _next_code(codes: list[str]) -> str:
    nums = [int(c.split("-")[1]) for c in codes if c.startswith("NP-") and c.split("-")[1].isdigit()]
    return f"NP-{(max(nums) + 1 if nums else 1):04d}"


@router.post("/items")
def add_item(request: Request, code: str = Form(...), name: str = Form(...), note: str = Form(""),
             user: User = Depends(current_user), s: Session = Depends(get_db)):
    code = code.strip().upper()
    if not is_item_code(code):
        raise BusinessError("품목코드는 'NP-0001' 형식이어야 합니다.")
    if s.get(Item, code):
        raise BusinessError(f"이미 있는 품목코드입니다: {code}")
    s.add(Item(code=code, name=name.strip(), note=note.strip()))
    s.commit()
    flash(request, f"{code} {name} 을(를) 등록했습니다.")
    return redirect("/items")


@router.post("/items/{code}")
def update_item(request: Request, code: str, name: str = Form(...), note: str = Form(""), active: bool = Form(False),
                user: User = Depends(current_user), s: Session = Depends(get_db)):
    item = s.get(Item, code)
    if item is None:
        raise BusinessError(f"품목이 없습니다: {code}")
    item.name, item.note, item.active = name.strip(), note.strip(), active
    s.commit()
    flash(request, f"{code} 을(를) 저장했습니다.")
    return redirect(f"/items?q={code}&show=all")

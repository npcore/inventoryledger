"""입고 / 타계정대체 / 보관처 이동."""

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..importers import import_receipts
from ..models import Location, Move, Receipt, Transfer, User
from ..services import BusinessError, check_editable
from ..web import (current_user, entry_context, flash, get_db, parse_date, redirect, render, require_item,
                   resolve_period)

router = APIRouter()

TRANSFER_ACCOUNTS = ["광고선전비", "견본비", "접대비", "소모품비", "연구개발비", "기타"]


def _in_period(model, p):
    return select(model).where(model.date.between(p.start_date, p.end_date)).order_by(model.date.desc(), model.id.desc())


def _location(s: Session, location_id: int) -> Location:
    loc = s.get(Location, location_id)
    if loc is None:
        raise BusinessError("보관처를 선택하세요.")
    return loc


def _positive(qty: int) -> int:
    if qty <= 0:
        raise BusinessError("수량은 1 이상이어야 합니다.")
    return qty


# 입고

@router.get("/receipts")
def receipts(request: Request, period_id: int | None = None, user: User = Depends(current_user),
             s: Session = Depends(get_db)):
    p = resolve_period(s, period_id)
    rows = s.scalars(_in_period(Receipt, p)).all()
    return render(request, "receipts.html", user=user, rows=rows, **entry_context(s, p))


@router.post("/receipts")
def add_receipt(request: Request, date: str = Form(...), item_code: str = Form(...), location_id: int = Form(...),
                qty: int = Form(...), amount: int = Form(...), vendor: str = Form(""), voucher_no: str = Form(""),
                note: str = Form(""), user: User = Depends(current_user), s: Session = Depends(get_db)):
    d = parse_date(date)
    check_editable(s, d)
    item = require_item(s, item_code)
    if amount < 0:
        raise BusinessError("입고금액은 0 이상이어야 합니다.")
    s.add(Receipt(date=d, item_code=item.code, location_id=_location(s, location_id).id, qty=_positive(qty),
                  amount=amount, vendor=vendor.strip(), voucher_no=voucher_no.strip(), note=note.strip(),
                  created_by=user.name))
    s.commit()
    flash(request, f"입고 등록: {item.code} {item.name} {qty:,}개 / {amount:,}원")
    return redirect("/receipts")


@router.post("/receipts/import")
async def upload_receipts(request: Request, file: UploadFile = File(...), user: User = Depends(current_user),
                          s: Session = Depends(get_db)):
    res = import_receipts(s, file.filename or "", await file.read(), user.name)
    s.commit()
    flash(request, f"엑셀 입고 가져오기 완료: {res.summary()}")
    for msg in res.skipped[:20]:
        flash(request, msg, "warn")
    return redirect("/receipts")


@router.post("/receipts/{rid}/delete")
def delete_receipt(request: Request, rid: int, user: User = Depends(current_user), s: Session = Depends(get_db)):
    e = s.get(Receipt, rid)
    if e:
        check_editable(s, e.date)
        s.delete(e)
        s.commit()
        flash(request, "입고 내역을 삭제했습니다.")
    return redirect(request.headers.get("referer", "/receipts"))


# 타계정대체

@router.get("/transfers")
def transfers(request: Request, period_id: int | None = None, user: User = Depends(current_user),
              s: Session = Depends(get_db)):
    p = resolve_period(s, period_id)
    rows = s.scalars(_in_period(Transfer, p)).all()
    return render(request, "transfers.html", user=user, rows=rows, accounts=TRANSFER_ACCOUNTS, **entry_context(s, p))


@router.post("/transfers")
def add_transfer(request: Request, date: str = Form(...), item_code: str = Form(...), location_id: int = Form(...),
                 qty: int = Form(...), account: str = Form(...), note: str = Form(""),
                 user: User = Depends(current_user), s: Session = Depends(get_db)):
    d = parse_date(date)
    check_editable(s, d)
    item = require_item(s, item_code)
    if not account.strip():
        raise BusinessError("대체 계정을 입력하세요.")
    s.add(Transfer(date=d, item_code=item.code, location_id=_location(s, location_id).id, qty=_positive(qty),
                   account=account.strip(), note=note.strip(), created_by=user.name))
    s.commit()
    flash(request, f"타계정대체 등록: {item.code} {item.name} {qty:,}개 → {account}")
    return redirect("/transfers")


@router.post("/transfers/{tid}/delete")
def delete_transfer(request: Request, tid: int, user: User = Depends(current_user), s: Session = Depends(get_db)):
    e = s.get(Transfer, tid)
    if e:
        check_editable(s, e.date)
        s.delete(e)
        s.commit()
        flash(request, "타계정대체 내역을 삭제했습니다.")
    return redirect(request.headers.get("referer", "/transfers"))


# 보관처 이동

@router.get("/moves")
def moves(request: Request, period_id: int | None = None, user: User = Depends(current_user),
          s: Session = Depends(get_db)):
    p = resolve_period(s, period_id)
    rows = s.scalars(_in_period(Move, p)).all()
    return render(request, "moves.html", user=user, rows=rows, **entry_context(s, p))


@router.post("/moves")
def add_move(request: Request, date: str = Form(...), item_code: str = Form(...), from_location_id: int = Form(...),
             to_location_id: int = Form(...), qty: int = Form(...), note: str = Form(""),
             user: User = Depends(current_user), s: Session = Depends(get_db)):
    d = parse_date(date)
    check_editable(s, d)
    item = require_item(s, item_code)
    src, dst = _location(s, from_location_id), _location(s, to_location_id)
    if src.id == dst.id:
        raise BusinessError("출발지와 도착지가 같습니다.")
    s.add(Move(date=d, item_code=item.code, from_location_id=src.id, to_location_id=dst.id, qty=_positive(qty),
               note=note.strip(), created_by=user.name))
    s.commit()
    flash(request, f"이동 등록: {item.code} {qty:,}개 {src.name} → {dst.name}")
    return redirect("/moves")


@router.post("/moves/{mid}/delete")
def delete_move(request: Request, mid: int, user: User = Depends(current_user), s: Session = Depends(get_db)):
    e = s.get(Move, mid)
    if e:
        check_editable(s, e.date)
        s.delete(e)
        s.commit()
        flash(request, "이동 내역을 삭제했습니다.")
    return redirect(request.headers.get("referer", "/moves"))

"""결산 기간: 수불부, 실사, 대사, 마감, 엑셀."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .. import services
from ..exporter import build_workbook
from ..importers import import_journal, import_legacy
from ..ledger import totals
from ..models import Period, User
from ..services import BusinessError
from ..web import admin_user, current_user, flash, get_db, redirect, render

router = APIRouter()


def _period(s: Session, pid: int) -> Period:
    p = s.get(Period, pid)
    if p is None:
        raise BusinessError("결산 기간이 없습니다.")
    return p


@router.get("/periods")
def periods(request: Request, user: User = Depends(current_user), s: Session = Depends(get_db)):
    return render(request, "periods.html", user=user, periods=services.periods(s))


@router.post("/periods/next")
def create_next(request: Request, user: User = Depends(current_user), s: Session = Depends(get_db)):
    p = services.create_next_period(s)
    s.commit()
    flash(request, f"{p.name} ({p.start_date} ~ {p.end_date}) 기간을 만들었습니다.")
    return redirect(f"/periods/{p.id}")


@router.post("/periods/import-legacy")
async def upload_legacy(request: Request, file: UploadFile = File(...), user: User = Depends(admin_user),
                        s: Session = Depends(get_db)):
    p, res = import_legacy(s, file.filename or "", await file.read(), user.name)
    s.commit()
    flash(request, f"{p.name} 기준 기간을 가져왔습니다: {res.summary()}")
    return redirect(f"/periods/{p.id}")


@router.get("/periods/{pid}")
def ledger(request: Request, pid: int, user: User = Depends(current_user), s: Session = Depends(get_db)):
    p = _period(s, pid)
    rows = services.ledger_rows(s, p)
    return render(request, "ledger.html", user=user, period=p, rows=rows, t=totals(rows),
                  prev=services.prev_period(s, p), next=services.next_period(s, p))


@router.get("/periods/{pid}/count")
def count_form(request: Request, pid: int, user: User = Depends(current_user), s: Session = Depends(get_db)):
    p = _period(s, pid)
    rows = [r for r in services.ledger_rows(s, p) if r.open_qty + r.in_qty > 0 or r.count_qty]
    return render(request, "count.html", user=user, period=p, rows=rows, locations=services.ensure_locations(s),
                  counts=services.counts_by_location(s, p), expected=services.expected_by_location(s, p))


@router.post("/periods/{pid}/count")
async def save_count(request: Request, pid: int, user: User = Depends(current_user), s: Session = Depends(get_db)):
    p = _period(s, pid)
    form = await request.form()
    values: dict[tuple[str, int], int | None] = {}
    for key, raw in form.items():
        if not key.startswith("c__"):
            continue
        _, code, loc = key.split("__")
        raw = str(raw).replace(",", "").strip()
        if raw and not raw.lstrip("-").isdigit():
            raise BusinessError(f"{code}: 숫자가 아닙니다 ({raw})")
        values[(code, int(loc))] = int(raw) if raw else None
    services.save_counts(s, p, values)
    s.commit()
    flash(request, "실사 수량을 저장했습니다.")
    return redirect(f"/periods/{pid}/count")


@router.get("/periods/{pid}/reconcile")
def reconcile(request: Request, pid: int, user: User = Depends(current_user), s: Session = Depends(get_db)):
    p = _period(s, pid)
    rows = services.reconcile(s, p)
    return render(request, "reconcile.html", user=user, period=p, rows=rows,
                  receipt_total=sum(r.receipt_amount for r in rows), journal_total=sum(r.journal_amount for r in rows))


@router.post("/periods/{pid}/journal")
async def upload_journal(request: Request, pid: int, file: UploadFile = File(...),
                         user: User = Depends(current_user), s: Session = Depends(get_db)):
    p = _period(s, pid)
    res = import_journal(s, p, file.filename or "", await file.read())
    s.commit()
    flash(request, f"분개장을 올렸습니다: {res.summary()}")
    for msg in res.skipped[:20]:
        flash(request, msg, "warn")
    return redirect(f"/periods/{pid}/reconcile")


@router.post("/periods/{pid}/close")
def close(request: Request, pid: int, user: User = Depends(current_user), s: Session = Depends(get_db)):
    p = _period(s, pid)
    services.close_period(s, p, user.name)
    s.commit()
    flash(request, f"{p.name} 마감 완료. 기말재고가 다음 기간 기초재고로 확정되었습니다.")
    return redirect(f"/periods/{pid}")


@router.post("/periods/{pid}/reopen")
def reopen(request: Request, pid: int, user: User = Depends(admin_user), s: Session = Depends(get_db)):
    p = _period(s, pid)
    services.reopen_period(s, p)
    s.commit()
    flash(request, f"{p.name} 마감을 취소했습니다.", "warn")
    return redirect(f"/periods/{pid}")


@router.get("/periods/{pid}/export.xlsx")
def export(pid: int, user: User = Depends(current_user), s: Session = Depends(get_db)):
    p = _period(s, pid)
    filename = f"재고수불 결산파일({p.name})_엔피코어.xlsx"
    return Response(
        build_workbook(s, p),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )

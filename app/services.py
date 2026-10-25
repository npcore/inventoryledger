"""기간·수불부 관련 업무 로직."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .ledger import LedgerRow
from .models import ClosingBalance, Count, Item, JournalLine, Location, Move, Period, Receipt, Transfer

DEFAULT_LOCATIONS = ["본사", "용인", "성남"]


class BusinessError(Exception):
    """사용자에게 그대로 보여줄 업무 규칙 위반."""


def quarter_end(d: date) -> date:
    q_last_month = ((d.month - 1) // 3 + 1) * 3
    next_month = date(d.year + (q_last_month == 12), q_last_month % 12 + 1, 1)
    return next_month - timedelta(days=1)


def quarter_name(d: date) -> str:
    return f"{d.year}.{(d.month - 1) // 3 + 1}Q"


def ensure_locations(s: Session) -> list[Location]:
    locs = s.scalars(select(Location).order_by(Location.sort_order, Location.id)).all()
    if not locs:
        for i, name in enumerate(DEFAULT_LOCATIONS):
            s.add(Location(name=name, sort_order=i))
        s.flush()
        locs = s.scalars(select(Location).order_by(Location.sort_order, Location.id)).all()
    return list(locs)


def periods(s: Session) -> list[Period]:
    return list(s.scalars(select(Period).order_by(Period.start_date.desc())))


def prev_period(s: Session, p: Period) -> Period | None:
    return s.scalar(select(Period).where(Period.end_date == p.start_date - timedelta(days=1)))


def next_period(s: Session, p: Period) -> Period | None:
    return s.scalar(select(Period).where(Period.start_date == p.end_date + timedelta(days=1)))


def current_period(s: Session) -> Period | None:
    """가장 오래된 미마감 기간 (없으면 최근 기간)."""
    return s.scalar(select(Period).where(Period.closed.is_(False)).order_by(Period.start_date)) or s.scalar(
        select(Period).order_by(Period.start_date.desc())
    )


def locked_until(s: Session) -> date | None:
    return s.scalar(select(func.max(Period.end_date)).where(Period.closed.is_(True)))


def check_editable(s: Session, d: date) -> None:
    lock = locked_until(s)
    if lock and d <= lock:
        raise BusinessError(f"{lock:%Y-%m-%d} 까지는 마감된 기간입니다. 기간 마감을 취소한 뒤 수정하세요.")


def create_next_period(s: Session) -> Period:
    last = s.scalar(select(Period).order_by(Period.end_date.desc()))
    if last is None:
        raise BusinessError("기준 기간이 없습니다. 먼저 기존 엑셀 결산 파일을 가져오세요.")
    start = last.end_date + timedelta(days=1)
    p = Period(name=quarter_name(start), start_date=start, end_date=quarter_end(start))
    s.add(p)
    s.flush()
    return p


def _receipt_sums(s: Session, start: date, end: date) -> dict[str, tuple[int, int]]:
    stmt = (
        select(Receipt.item_code, func.sum(Receipt.qty), func.sum(Receipt.amount))
        .where(Receipt.date.between(start, end))
        .group_by(Receipt.item_code)
    )
    return {code: (int(q), int(a)) for code, q, a in s.execute(stmt)}


def _transfer_lines(s: Session, start: date, end: date) -> dict[str, list[int]]:
    lines: dict[str, list[int]] = defaultdict(list)
    stmt = select(Transfer.item_code, Transfer.qty).where(Transfer.date.between(start, end)).order_by(Transfer.id)
    for code, q in s.execute(stmt):
        lines[code].append(q)
    return lines


def ledger_rows(s: Session, p: Period, include_empty: bool = False) -> list[LedgerRow]:
    names = dict(s.execute(select(Item.code, Item.name)).all())

    if p.legacy:
        rows = []
        for cb in s.scalars(select(ClosingBalance).where(ClosingBalance.period_id == p.id)):
            r = LedgerRow(cb.item_code, names.get(cb.item_code, ""), count_qty=cb.qty, counted=True)
            r.close_amount = cb.amount
            r.avg_cost = Decimal(cb.unit_cost)
            rows.append(r)
        return sorted(rows, key=lambda r: r.code)

    prev = prev_period(s, p)
    opening = (
        {cb.item_code: cb for cb in s.scalars(select(ClosingBalance).where(ClosingBalance.period_id == prev.id))}
        if prev
        else {}
    )
    receipts = _receipt_sums(s, p.start_date, p.end_date)
    transfers = _transfer_lines(s, p.start_date, p.end_date)
    counts: dict[str, int] = defaultdict(int)
    for code, qty in s.execute(select(Count.item_code, Count.qty).where(Count.period_id == p.id)):
        counts[code] += qty

    codes = set(names) if include_empty else set(opening) | set(receipts) | set(transfers) | set(counts)
    rows = []
    for code in sorted(codes):
        ob = opening.get(code)
        r = LedgerRow(
            code,
            names.get(code, ""),
            open_qty=ob.qty if ob else 0,
            open_amount=ob.amount if ob else 0,
            in_qty=receipts.get(code, (0, 0))[0],
            in_amount=receipts.get(code, (0, 0))[1],
            xfer_lines=transfers.get(code, []),
            count_qty=counts.get(code, 0),
            counted=code in counts,
        ).compute()
        if include_empty or not r.is_empty:
            rows.append(r)
    return rows


def counts_by_location(s: Session, p: Period) -> dict[tuple[str, int], int]:
    return {(c, l): q for c, l, q in s.execute(select(Count.item_code, Count.location_id, Count.qty).where(Count.period_id == p.id))}


def expected_by_location(s: Session, p: Period) -> dict[tuple[str, int], int]:
    """출고를 반영하지 않은 보관처별 장부 예상수량 (직전 실사 + 입고 - 대체 ± 이동).

    실사 역산 방식이라 출고가 빠져 있으므로 실사 시 참고용이다.
    """
    exp: dict[tuple[str, int], int] = defaultdict(int)
    prev = prev_period(s, p)
    if prev:
        for k, q in counts_by_location(s, prev).items():
            exp[k] += q
    rng = (p.start_date, p.end_date)
    for c, l, q in s.execute(select(Receipt.item_code, Receipt.location_id, Receipt.qty).where(Receipt.date.between(*rng))):
        exp[(c, l)] += q
    for c, l, q in s.execute(select(Transfer.item_code, Transfer.location_id, Transfer.qty).where(Transfer.date.between(*rng))):
        exp[(c, l)] -= q
    for c, f, t, q in s.execute(
        select(Move.item_code, Move.from_location_id, Move.to_location_id, Move.qty).where(Move.date.between(*rng))
    ):
        exp[(c, f)] -= q
        exp[(c, t)] += q
    return exp


def save_counts(s: Session, p: Period, values: dict[tuple[str, int], int | None]) -> None:
    """실사 수량 저장. None 은 '미입력'으로 삭제한다."""
    if p.closed:
        raise BusinessError("마감된 기간의 실사는 수정할 수 없습니다.")
    existing = {(c.item_code, c.location_id): c for c in s.scalars(select(Count).where(Count.period_id == p.id))}
    for (code, loc), qty in values.items():
        row = existing.get((code, loc))
        if qty is None:
            if row:
                s.delete(row)
        elif qty < 0:
            raise BusinessError(f"{code}: 실사 수량은 0 이상이어야 합니다.")
        elif row:
            row.qty = qty
        else:
            s.add(Count(period_id=p.id, item_code=code, location_id=loc, qty=qty))


def close_period(s: Session, p: Period, user: str) -> None:
    if p.closed:
        raise BusinessError("이미 마감된 기간입니다.")
    prev = prev_period(s, p)
    if prev and not prev.closed:
        raise BusinessError(f"이전 기간({prev.name})을 먼저 마감하세요.")
    rows = ledger_rows(s, p)
    errors = [f"{r.code} {r.name}: {e}" for r in rows for e in r.errors]
    if errors:
        raise BusinessError("오류가 있어 마감할 수 없습니다:\n" + "\n".join(errors))
    for r in rows:
        if r.count_qty or r.close_amount:
            s.add(ClosingBalance(period_id=p.id, item_code=r.code, qty=r.count_qty, unit_cost=str(r.avg_cost), amount=r.close_amount))
    p.closed = True
    p.closed_at = datetime.now()
    p.closed_by = user


def reopen_period(s: Session, p: Period) -> None:
    if not p.closed:
        raise BusinessError("마감되지 않은 기간입니다.")
    if p.legacy:
        raise BusinessError("엑셀에서 이관한 기준 기간은 마감 취소할 수 없습니다.")
    nxt = next_period(s, p)
    if nxt and nxt.closed:
        raise BusinessError(f"다음 기간({nxt.name})이 마감되어 있어 취소할 수 없습니다.")
    s.execute(delete(ClosingBalance).where(ClosingBalance.period_id == p.id))
    p.closed = False
    p.closed_at = None
    p.closed_by = None


RAW_MATERIAL_ACCOUNTS = {"153", "원재료"}


@dataclass
class ReconRow:
    date: date
    receipt_amount: int = 0
    journal_amount: int = 0
    receipts: list[Receipt] = field(default_factory=list)
    journals: list[JournalLine] = field(default_factory=list)

    @property
    def diff(self) -> int:
        return self.receipt_amount - self.journal_amount


def reconcile(s: Session, p: Period) -> list[ReconRow]:
    """입고장과 분개장(원재료 계정)을 일자별로 맞춰 본다."""
    by_date: dict[date, ReconRow] = {}
    for e in s.scalars(select(Receipt).where(Receipt.date.between(p.start_date, p.end_date)).order_by(Receipt.id)):
        row = by_date.setdefault(e.date, ReconRow(e.date))
        row.receipts.append(e)
        row.receipt_amount += e.amount
    for j in s.scalars(select(JournalLine).where(JournalLine.period_id == p.id).order_by(JournalLine.id)):
        if j.account_code in RAW_MATERIAL_ACCOUNTS or j.account_name in RAW_MATERIAL_ACCOUNTS:
            row = by_date.setdefault(j.date, ReconRow(j.date))
            row.journals.append(j)
            row.journal_amount += j.debit - j.credit
    return [by_date[d] for d in sorted(by_date)]

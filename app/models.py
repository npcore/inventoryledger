"""DB 모델.

재고 수량·금액은 정수(개, 원)로 저장한다. 평균단가만 소수가 필요하므로
마감 시 Decimal 문자열로 보관한다.
"""

from datetime import date, datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(50))
    password_hash: Mapped[str] = mapped_column(String(200))
    is_admin: Mapped[bool] = mapped_column(default=False)
    active: Mapped[bool] = mapped_column(default=True)


class Location(Base):
    """보관처 (본사/용인/성남)."""

    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    sort_order: Mapped[int] = mapped_column(default=0)


class Item(Base):
    __tablename__ = "items"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    note: Mapped[str] = mapped_column(String(200), default="")
    active: Mapped[bool] = mapped_column(default=True)


class Period(Base):
    """결산 기간. 마감되면 ClosingBalance 가 확정되고 기간 내 거래는 수정할 수 없다."""

    __tablename__ = "periods"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    start_date: Mapped[date]
    end_date: Mapped[date]
    closed: Mapped[bool] = mapped_column(default=False)
    # 엑셀에서 기말 잔액만 이관한 기간: 다시 계산하지 않는다.
    legacy: Mapped[bool] = mapped_column(default=False)
    closed_at: Mapped[datetime | None]
    closed_by: Mapped[str | None] = mapped_column(String(50))


class ClosingBalance(Base):
    __tablename__ = "closing_balances"
    __table_args__ = (UniqueConstraint("period_id", "item_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id", ondelete="CASCADE"))
    item_code: Mapped[str] = mapped_column(ForeignKey("items.code"))
    qty: Mapped[int]
    unit_cost: Mapped[str] = mapped_column(String(50))
    amount: Mapped[int]


class Count(Base):
    """기말 실사 수량 (보관처별)."""

    __tablename__ = "counts"
    __table_args__ = (UniqueConstraint("period_id", "item_code", "location_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id", ondelete="CASCADE"))
    item_code: Mapped[str] = mapped_column(ForeignKey("items.code"))
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    qty: Mapped[int]


class _Entry:
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date]
    qty: Mapped[int]
    note: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Receipt(_Entry, Base):
    """입고."""

    __tablename__ = "receipts"

    item_code: Mapped[str] = mapped_column(ForeignKey("items.code"))
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    amount: Mapped[int]
    vendor: Mapped[str] = mapped_column(String(100), default="")
    voucher_no: Mapped[str] = mapped_column(String(30), default="")

    item: Mapped[Item] = relationship(lazy="joined")
    location: Mapped[Location] = relationship(lazy="joined")


class Transfer(_Entry, Base):
    """타계정대체 (샘플·광고선전비 등). 금액은 결산 시 평균단가로 계산한다."""

    __tablename__ = "transfers"

    item_code: Mapped[str] = mapped_column(ForeignKey("items.code"))
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    account: Mapped[str] = mapped_column(String(50))

    item: Mapped[Item] = relationship(lazy="joined")
    location: Mapped[Location] = relationship(lazy="joined")


class Move(_Entry, Base):
    """보관처 간 이동. 수불부 금액에는 영향이 없고 보관처별 예상재고에만 쓰인다."""

    __tablename__ = "moves"

    item_code: Mapped[str] = mapped_column(ForeignKey("items.code"))
    from_location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    to_location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))

    item: Mapped[Item] = relationship(lazy="joined")
    from_location: Mapped[Location] = relationship(foreign_keys=[from_location_id], lazy="joined")
    to_location: Mapped[Location] = relationship(foreign_keys=[to_location_id], lazy="joined")


class JournalLine(Base):
    """회계 프로그램에서 받은 분개장 (입고장 대사용)."""

    __tablename__ = "journal_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id", ondelete="CASCADE"))
    date: Mapped[date]
    voucher_no: Mapped[str] = mapped_column(String(30), default="")
    side: Mapped[str] = mapped_column(String(10), default="")
    account_code: Mapped[str] = mapped_column(String(20), default="")
    account_name: Mapped[str] = mapped_column(String(50), default="")
    debit: Mapped[int] = mapped_column(default=0)
    credit: Mapped[int] = mapped_column(default=0)
    vendor: Mapped[str] = mapped_column(String(100), default="")
    memo: Mapped[str] = mapped_column(String(200), default="")

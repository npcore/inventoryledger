"""수불부 계산 (총평균법 + 실사 역산 출고).

    평균단가 = (기초금액 + 입고금액) / (기초수량 + 입고수량)
    대체금액 = Σ round(대체 건별 수량 × 평균단가)   (타계정대체 시트의 건별 금액 합과 일치)
    기말금액 = round(실사수량 × 평균단가)
    출고수량 = 기초수량 + 입고수량 - 대체수량 - 실사수량
    출고금액 = 기초금액 + 입고금액 - 대체금액 - 기말금액   (매출원가)

출고금액을 차액으로 잡아 원 단위 반올림 차이가 매출원가에 흡수되게 한다.
그래서 기초 + 입고 = 대체 + 출고 + 기말 이 항상 정확히 맞는다.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal


def to_won(x: Decimal) -> int:
    return int(x.quantize(Decimal(1), rounding=ROUND_HALF_UP))


@dataclass
class LedgerRow:
    code: str
    name: str
    open_qty: int = 0
    open_amount: int = 0
    in_qty: int = 0
    in_amount: int = 0
    xfer_lines: list[int] = field(default_factory=list)  # 타계정대체 건별 수량
    count_qty: int = 0
    counted: bool = False  # 실사 입력 여부 (0개 입력과 미입력 구분)

    avg_cost: Decimal = Decimal(0)
    xfer_qty: int = 0
    xfer_amount: int = 0
    out_qty: int = 0
    out_amount: int = 0
    close_amount: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def in_cost(self) -> Decimal:
        return Decimal(self.in_amount) / self.in_qty if self.in_qty else Decimal(0)

    @property
    def open_cost(self) -> Decimal:
        return Decimal(self.open_amount) / self.open_qty if self.open_qty else Decimal(0)

    def compute(self) -> "LedgerRow":
        avail_qty = self.open_qty + self.in_qty
        avail_amount = self.open_amount + self.in_amount
        self.avg_cost = Decimal(avail_amount) / avail_qty if avail_qty > 0 else Decimal(0)
        self.xfer_qty = sum(self.xfer_lines)
        self.xfer_amount = sum(to_won(q * self.avg_cost) for q in self.xfer_lines)
        self.close_amount = to_won(self.count_qty * self.avg_cost)
        self.out_qty = avail_qty - self.xfer_qty - self.count_qty
        self.out_amount = avail_amount - self.xfer_amount - self.close_amount

        self.errors.clear()
        self.warnings.clear()
        if avail_qty <= 0 and (self.xfer_qty or self.count_qty):
            self.errors.append("기초·입고 수량이 없는데 대체/실사 수량이 있습니다 (단가 없음)")
        elif self.out_qty < 0:
            self.errors.append(f"실사+대체가 기초+입고보다 {-self.out_qty}개 많습니다 (입고 누락?)")
        if avail_qty > 0 and not self.counted:
            self.warnings.append("실사 미입력 — 전량 출고로 처리됩니다")
        return self

    @property
    def is_empty(self) -> bool:
        return not any((self.open_qty, self.open_amount, self.in_qty, self.in_amount, self.xfer_lines, self.count_qty))


@dataclass
class LedgerTotals:
    open_qty: int = 0
    open_amount: int = 0
    in_qty: int = 0
    in_amount: int = 0
    xfer_qty: int = 0
    xfer_amount: int = 0
    out_qty: int = 0
    out_amount: int = 0
    count_qty: int = 0
    close_amount: int = 0


def totals(rows: list[LedgerRow]) -> LedgerTotals:
    t = LedgerTotals()
    for r in rows:
        for f in t.__dataclass_fields__:
            setattr(t, f, getattr(t, f) + getattr(r, f))
    return t

from decimal import Decimal

from app.ledger import LedgerRow, totals


def test_total_average_and_derived_outflow():
    r = LedgerRow("NP-0001", "x", open_qty=95, open_amount=1_146_214_142, in_qty=27, in_amount=381_900_000,
                  count_qty=119, counted=True).compute()
    assert r.avg_cost == Decimal(1_146_214_142 + 381_900_000) / 122
    assert r.out_qty == 3
    assert r.close_amount == 1_490_537_565  # 기존 결산파일 NP-0032 기말금액과 동일
    # 기초 + 입고 = 대체 + 출고 + 기말 (원 단위로 정확히)
    assert r.open_amount + r.in_amount == r.xfer_amount + r.out_amount + r.close_amount
    assert not r.errors and not r.warnings


def test_transfer_amount_rounds_per_line():
    # 건별로 반올림하므로 0.4원 × 3건 = 0원 (합계 1.2원을 한 번에 반올림한 1원이 아님)
    r = LedgerRow("A", "x", in_qty=10, in_amount=4, xfer_lines=[1, 1, 1], count_qty=7, counted=True).compute()
    assert r.avg_cost == Decimal("0.4")
    assert r.xfer_amount == 0
    assert r.xfer_qty == 3
    assert r.close_amount == 3  # 2.8 → 3
    assert r.out_amount == 1
    assert r.open_amount + r.in_amount == r.xfer_amount + r.out_amount + r.close_amount


def test_count_exceeding_available_is_error():
    r = LedgerRow("A", "x", open_qty=5, open_amount=500, count_qty=6, counted=True).compute()
    assert r.out_qty == -1
    assert r.errors


def test_count_without_any_cost_is_error():
    r = LedgerRow("A", "x", count_qty=1, counted=True).compute()
    assert r.errors


def test_uncounted_item_warns_and_is_fully_issued():
    r = LedgerRow("A", "x", open_qty=5, open_amount=500).compute()
    assert r.warnings and not r.errors
    assert r.out_qty == 5 and r.out_amount == 500 and r.close_amount == 0


def test_totals():
    rows = [LedgerRow("A", "", open_qty=1, open_amount=10, count_qty=1, counted=True).compute(),
            LedgerRow("B", "", in_qty=2, in_amount=30, count_qty=0, counted=True).compute()]
    t = totals(rows)
    assert (t.open_amount, t.in_amount, t.close_amount, t.out_amount, t.out_qty) == (10, 30, 10, 30, 2)

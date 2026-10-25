"""실제 결산 파일과 계산 결과 비교.

회사 자료라 저장소에 넣지 않는다. 경로를 주면 실행된다:
    INVENTORY_REFERENCE_XLS="/path/재고수불 결산파일(2026.2Q)_엔피코어.xls" uv run pytest tests/test_reference_file.py
"""

import os
from collections import defaultdict
from pathlib import Path

import pytest

from app.importers import is_item_code, latest_suffix, load_workbook, table, text, to_int
from app.ledger import LedgerRow, totals

PATH = os.environ.get("INVENTORY_REFERENCE_XLS")

# 2026.06 파일의 타계정대체 시트가 NP-0436 에 평균단가(1,508.36) 대신 다른 품목(PANDA)의
# 2025.12 단가(1,509.82)를 써서 2원 차이가 난다. 프로그램은 총평균 단가를 쓴다.
KNOWN_XFER_PRICE_ERRORS = {"NP-0436": 2}
pytestmark = pytest.mark.skipif(not PATH, reason="INVENTORY_REFERENCE_XLS 미지정")


def test_ledger_matches_reference_file():
    sheets = load_workbook(PATH, Path(PATH).read_bytes())
    suffix = latest_suffix(list(sheets))
    xfer_lines = defaultdict(list)
    for _, r in table(sheets[f"타계정대체({suffix})"], ["품목코드", "대체수량"]):
        if is_item_code(r["품목코드"]):
            xfer_lines[text(r["품목코드"])].append(to_int(r["대체수량"]))

    rows, expected = [], []
    for _, r in table(sheets[f"수불부({suffix})"], ["품목코드", "기말금액"]):
        if not is_item_code(r["품목코드"]):
            continue
        code = text(r["품목코드"])
        row = LedgerRow(code, "", open_qty=to_int(r["기초수량"]), open_amount=to_int(r["기초금액"]),
                        in_qty=to_int(r["입고수량"]), in_amount=to_int(r["입고금액"]), xfer_lines=xfer_lines[code],
                        count_qty=to_int(r["기말수량"]), counted=True).compute()
        rows.append(row)
        expected.append((code, to_int(r["출고수량"]), r["출고금액"] or 0, to_int(r["대체금액"]), to_int(r["기말금액"])))

    for row, (code, out_qty, out_amount, xfer_amount, close_amount) in zip(rows, expected):
        assert row.out_qty == out_qty, code
        if code in KNOWN_XFER_PRICE_ERRORS:
            assert abs(row.xfer_amount - xfer_amount) <= KNOWN_XFER_PRICE_ERRORS[code], code
        else:
            assert row.xfer_amount == xfer_amount, code
        # 엑셀은 기초금액에 원 미만(수량×단가)을 들고 다니므로 원 단위 반올림 결과가 1원까지 다를 수 있다.
        # 프로그램은 전기 기말금액(원 단위)을 그대로 기초로 쓴다.
        assert abs(row.close_amount - close_amount) <= 1, code
        assert abs(row.out_amount - out_amount) <= 1, code
        assert not row.errors, (code, row.errors)

    t = totals(rows)
    assert abs(t.close_amount - sum(e[4] for e in expected)) <= 5

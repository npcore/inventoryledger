import io
from datetime import date

import openpyxl
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app import db


@pytest.fixture
def engine(tmp_path, monkeypatch):
    eng = db.make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", sessionmaker(bind=eng, expire_on_commit=False))
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    db.init_db(eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture
def client(engine):
    from app.main import create_app
    from app.ratelimit import login_limiter

    login_limiter._failures.clear()
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def admin(client):
    r = client.post("/setup", data={"username": "admin", "name": "관리자", "password": "password123"})
    assert r.status_code == 200
    return client


def xlsx(sheets: dict[str, list[list]]) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def legacy_file() -> bytes:
    """기존 결산 파일과 같은 구조의 작은 샘플 (2026.06 기말)."""
    blank = [None] * 17
    return xlsx({
        "원재료 코드표": [[], [None, "품목코드", "품목명", "비고"],
                       [None, "NP-0001", "RAM : DDR4 32GB"], [None, "NP-0002", "SSD : 960G"],
                       [None, "NP-0003", "케이블 : SAS"], [None, "NP-0499", 0]],
        "수불부(2026.06)": [
            blank,
            [None, None, None, date(2025, 12, 31)] + [None] * 12 + [date(2026, 6, 30)],
            [None, "품목코드", "품목명", "기초수량", "기초단가", "기초금액", "입고수량", "입고단가", "입고금액", "평균단가",
             "대체수량", "대체금액", "출고수량", "출고금액", "기말수량", "기말단가", "기말금액"],
            [None, "NP-0001", "RAM : DDR4 32GB"] + [0] * 11 + [10, 100000, 1000000],
            [None, "NP-0002", "SSD : 960G"] + [0] * 11 + [3, 333333.3333, 1000000],
            [None, "NP-0003", "케이블 : SAS"] + [0] * 14,
            [None, "합계", None, 0, None, 0, 0, None, 0, None, 0, 0, 0, 0, 13, None, 2000000],
        ],
        "재고실사(2026.06)": [
            ["재고현황 (기준일 : 2026.06.30)"],
            ["품목코드", "품목명", "재고수량", "단가", "합계", "비고", None, "본사", "용인", "성남", "비고"],
            ["NP-0001", "RAM : DDR4 32GB", 10, 100000, 1000000, None, None, 4, 6, 0, 1],
            ["NP-0002", "SSD : 960G", 3, 333333.33, 1000000, None, None, 0, 0, 3, 1],
            ["합계", None, 13, None, 2000000],
        ],
    })

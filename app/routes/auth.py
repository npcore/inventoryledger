import logging

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import hash_password, verify_password
from ..models import User
from ..ratelimit import IP_LIMIT, USER_LIMIT, login_limiter
from ..services import BusinessError
from ..web import admin_user, current_user, flash, get_db, redirect, render

router = APIRouter()
log = logging.getLogger("uvicorn.error")


def _has_users(s: Session) -> bool:
    return bool(s.scalar(select(func.count(User.id))))


@router.get("/login")
def login_form(request: Request, s: Session = Depends(get_db)):
    if not _has_users(s):
        return redirect("/setup")
    return render(request, "login.html")


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), s: Session = Depends(get_db)):
    username = username.strip()
    ip = request.client.host if request.client else "?"
    keys = [(f"user:{username.lower()}", USER_LIMIT), (f"ip:{ip}", IP_LIMIT)]
    if wait := max(login_limiter.blocked_for(k, limit) for k, limit in keys):
        flash(request, f"로그인 실패가 많아 잠시 막혔습니다. {wait // 60 + 1}분 뒤에 다시 시도하세요.", "error")
        return redirect("/login")

    user = s.scalar(select(User).where(User.username == username))
    if user is None or not user.active or not verify_password(password, user.password_hash):
        for k, _ in keys:
            login_limiter.fail(k)
        log.warning("로그인 실패: username=%r ip=%s", username, ip)
        flash(request, "아이디 또는 비밀번호가 올바르지 않습니다.", "error")
        return redirect("/login")
    login_limiter.reset(keys[0][0])
    request.session.clear()
    request.session["uid"] = user.id
    return redirect("/")


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return redirect("/login")


@router.get("/setup")
def setup_form(request: Request, s: Session = Depends(get_db)):
    if _has_users(s):
        return redirect("/login")
    return render(request, "setup.html")


@router.post("/setup")
def setup(request: Request, username: str = Form(...), name: str = Form(...), password: str = Form(...),
          s: Session = Depends(get_db)):
    if _has_users(s):
        return redirect("/login")
    _validate_password(password)
    user = User(username=username.strip(), name=name.strip(), password_hash=hash_password(password), is_admin=True)
    s.add(user)
    s.commit()
    request.session["uid"] = user.id
    flash(request, "관리자 계정을 만들었습니다.")
    return redirect("/")


def _validate_password(password: str) -> None:
    if len(password) < 8:
        raise BusinessError("비밀번호는 8자 이상이어야 합니다.")


@router.get("/users")
def users(request: Request, user: User = Depends(admin_user), s: Session = Depends(get_db)):
    return render(request, "users.html", user=user, users=s.scalars(select(User).order_by(User.id)).all())


@router.post("/users")
def add_user(request: Request, username: str = Form(...), name: str = Form(...), password: str = Form(...),
             is_admin: bool = Form(False), user: User = Depends(admin_user), s: Session = Depends(get_db)):
    _validate_password(password)
    if s.scalar(select(User).where(User.username == username.strip())):
        raise BusinessError(f"이미 있는 아이디입니다: {username}")
    s.add(User(username=username.strip(), name=name.strip(), password_hash=hash_password(password), is_admin=is_admin))
    s.commit()
    flash(request, f"사용자 {name}을(를) 추가했습니다.")
    return redirect("/users")


@router.post("/users/{uid}")
def update_user(request: Request, uid: int, password: str = Form(""), active: bool = Form(False),
                is_admin: bool = Form(False), user: User = Depends(admin_user), s: Session = Depends(get_db)):
    target = s.get(User, uid)
    if target is None:
        raise BusinessError("사용자가 없습니다.")
    if target.id == user.id and (not active or not is_admin):
        raise BusinessError("본인 계정의 관리자 권한/사용 여부는 바꿀 수 없습니다.")
    if password:
        _validate_password(password)
        target.password_hash = hash_password(password)
    target.active, target.is_admin = active, is_admin
    s.commit()
    flash(request, f"{target.name} 정보를 저장했습니다.")
    return redirect("/users")


@router.get("/me")
def me(request: Request, user: User = Depends(current_user)):
    return render(request, "me.html", user=user)


@router.post("/me")
def change_password(request: Request, current: str = Form(...), password: str = Form(...),
                    user: User = Depends(current_user), s: Session = Depends(get_db)):
    if not verify_password(current, user.password_hash):
        raise BusinessError("현재 비밀번호가 올바르지 않습니다.")
    _validate_password(password)
    user.password_hash = hash_password(password)
    s.commit()
    flash(request, "비밀번호를 변경했습니다.")
    return redirect("/me")

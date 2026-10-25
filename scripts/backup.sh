#!/usr/bin/env bash
# 실행 중인 컨테이너의 DB를 안전하게(온라인 백업 API) 복사해 backups/ 에 날짜별로 남긴다.
# 사용: sudo ./scripts/backup.sh            (보관 기간 기본 90일)
#       sudo KEEP_DAYS=30 ./scripts/backup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

KEEP_DAYS="${KEEP_DAYS:-90}"
ts="$(date +%Y%m%d-%H%M%S)"
mkdir -p backups

docker compose exec -T app python -c "
import sqlite3
src = sqlite3.connect('/data/inventory.db')
dst = sqlite3.connect('/data/backup-tmp.db')
src.backup(dst)
dst.close()
"
mv data/backup-tmp.db "backups/inventory-${ts}.db"
find backups -name 'inventory-*.db' -mtime "+${KEEP_DAYS}" -delete
echo "백업 완료: backups/inventory-${ts}.db"

# 외부 보관: rclone에 Google Drive 리모트(gdrive)가 설정돼 있으면 복사한다.
# 서버 고장에 대비한 사본이라 sync가 아닌 copy를 쓴다 (서버 쪽 삭제가 번지지 않게).
OFFSITE="${OFFSITE:-gdrive:재고수불-백업}"
OFFSITE_KEEP_DAYS="${OFFSITE_KEEP_DAYS:-365}"
RCLONE="$(command -v rclone || echo "$HOME/.local/bin/rclone")"
if [ -x "$RCLONE" ] && "$RCLONE" listremotes | grep -qx "${OFFSITE%%:*}:"; then
  if "$RCLONE" copy backups "$OFFSITE" --include 'inventory-*.db' \
     && "$RCLONE" delete "$OFFSITE" --include 'inventory-*.db' --min-age "${OFFSITE_KEEP_DAYS}d"; then
    echo "외부 복사 완료: ${OFFSITE}"
  else
    echo "외부 복사 실패: ${OFFSITE} (로컬 백업은 정상)" >&2
    exit 1
  fi
fi

#!/bin/bash
set -e

LOCAL_DIR="${DEPLOY_LOCAL_DIR:-$(cd "$(dirname "$0")" && pwd)/}"
REMOTE_HOST="${DEPLOY_REMOTE_HOST:-}"
REMOTE_DIR="${DEPLOY_REMOTE_DIR:-}"

if [ -z "$REMOTE_HOST" ] || [ -z "$REMOTE_DIR" ]; then
  echo "错误：请设置环境变量 DEPLOY_REMOTE_HOST 和 DEPLOY_REMOTE_DIR" >&2
  echo "示例：" >&2
  echo "  export DEPLOY_REMOTE_HOST=user@your-server-ip" >&2
  echo "  export DEPLOY_REMOTE_DIR=/home/user/telegram-ai-chat" >&2
  exit 1
fi

echo "==> Syncing project to server..."
rsync -av \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='.env' \
  --exclude='sessions' \
  --exclude='chat.log' \
  --exclude='strategy.log' \
  --exclude='.bot.pid' \
  "$LOCAL_DIR" \
  "${REMOTE_HOST}:${REMOTE_DIR}/"

echo "==> Restarting docker compose on server..."
ssh "$REMOTE_HOST" "cd ${REMOTE_DIR} && docker compose down && docker compose up -d --build"

echo "==> Deploy finished"

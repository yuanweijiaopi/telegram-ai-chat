#!/bin/bash
set -e

LOCAL_DIR="REDACTED_LOCAL_PATH"
REMOTE_HOST="root@REDACTED_IP"
REMOTE_DIR="/root/telegram-ai-chat"

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

#!/usr/bin/env bash
# Dev: запуск бота с автоперезапуском при изменении *.py в bot/ и config/.
# Требует: из корня репо (где bot/ и config/).
set -e
cd "$(dirname "$0")/.."

if command -v watchfiles >/dev/null 2>&1; then
  echo "Using watchfiles for hot reload (bot + config)..."
  watchfiles 'python -m bot.main' bot config
else
  echo "Run: pip install watchfiles  for hot reload. Starting once..."
  exec python -m bot.main
fi

#!/usr/bin/env bash
# Кладёт метрики в METRICS.md ветки metrics — страница открывается прямо в GitHub, ссылка в README.
#   bash checks/core/publish_metrics_file.sh metrics.md
set -euo pipefail
src=$(realpath "$1")
git config user.name "github-actions[bot]"
git config user.email "41898283+github-actions[bot]@users.noreply.github.com"
for attempt in 1 2 3 4 5; do
  rm -rf mp && git worktree prune
  if git ls-remote --exit-code origin metrics >/dev/null; then
    git fetch -q --depth=1 origin metrics && git worktree add -q mp origin/metrics && git -C mp checkout -q -B metrics
  else
    git worktree add -q --orphan -b metrics mp
  fi
  cp "$src" mp/METRICS.md
  git -C mp add METRICS.md
  if git -C mp diff --cached --quiet; then
    echo "метрики не изменились"
    exit 0
  fi
  git -C mp commit -qm "metrics: METRICS.md"
  if git -C mp push -q origin metrics; then
    echo "METRICS.md обновлён"
    exit 0
  fi
  echo "ветку metrics обновили параллельно — попытка $attempt, повторяю"
  sleep $((attempt * 3))
done
echo "::warning::METRICS.md записать не удалось после 5 попыток"

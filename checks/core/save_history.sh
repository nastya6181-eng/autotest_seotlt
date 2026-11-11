#!/usr/bin/env bash
# Дописывает прогон в history/runs.jsonl ветки metrics и пушит; при гонке двух прогонов — повтор поверх свежей ветки.
#   bash checks/core/save_history.sh collected content|design
set -euo pipefail
collected=$1 workflow=$2
git config user.name "github-actions[bot]"
git config user.email "41898283+github-actions[bot]@users.noreply.github.com"
for attempt in 1 2 3 4 5; do
  rm -rf m && git worktree prune
  if git ls-remote --exit-code --heads origin metrics >/dev/null; then
    git fetch -q --depth=1 origin metrics && git worktree add -q m origin/metrics && git -C m checkout -q -B metrics
  else
    git worktree add -q --orphan -b metrics m
  fi
  python checks/core/history.py append "$collected" m/history/runs.jsonl --workflow "$workflow"
  git -C m add history
  if git -C m diff --cached --quiet; then
    echo "нечего записывать"
    exit 0
  fi
  git -C m commit -qm "metrics: $workflow run ${GITHUB_RUN_ID:-local}"
  if git -C m push -q origin metrics; then
    exit 0
  fi
  echo "ветку metrics обновили параллельно — попытка $attempt, повторяю"
  sleep $((attempt * 3))
done
echo "::warning::историю записать не удалось после 5 попыток"

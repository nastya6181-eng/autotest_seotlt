#!/usr/bin/env bash
# Закреплённая задача «📊 Метрики»: создаёт при первом запуске, дальше переписывает текст.
#   bash checks/core/publish_metrics_issue.sh metrics.md
set -euo pipefail
body=$1
title="📊 Метрики автотестов"
gh label create metrics --color 0E8A16 --description "Задача с метриками, обновляется автоматически" 2>/dev/null || true
number=$(gh issue list --label metrics --state open --json number --jq '.[0].number // empty')
if [ -z "$number" ]; then
  url=$(gh issue create --title "$title" --label metrics --body-file "$body")
  number=${url##*/}
  echo "создана задача #$number"
else
  gh issue edit "$number" --title "$title" --body-file "$body" >/dev/null
  echo "обновлена задача #$number"
fi
gh issue pin "$number" 2>/dev/null || echo "::notice::закрепить задачу #$number не вышло — закрепи вручную: открыть задачу → Pin issue"

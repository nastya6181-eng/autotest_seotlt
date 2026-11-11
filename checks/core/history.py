#!/usr/bin/env python3
"""История прогонов для метрик: ветка metrics, файл history/runs.jsonl — строка JSON на сайт (страницу) в прогоне.

    python checks/core/history.py append collected/ m/history/runs.jsonl --workflow content
    python checks/core/history.py append collected/ m/history/runs.jsonl --workflow design

JSON Lines, а не CSV: новые правила добавляются без съезда колонок. Старые history/<сайт>.csv читаются load().
"""
import argparse
import csv
import glob
import json
import os
import sys

FIELDS = ("pages", "pages_failed", "urls_checked", "duration_s", "failed", "rules_failed", "rules_total")


def record(summary, workflow, run_id="", run_url=""):
    """Строка истории из summary.json одного сайта (или одной страницы макета)."""
    site, _, page = summary["project"].partition(" · ")
    u = summary.get("findings_unique", {})
    return {
        "workflow": workflow,
        "site": site if page else summary["project_key"],  # у макета project — «сайт · страница»
        "page": page or None,
        "started_at": summary["started_at"],
        "run_id": str(run_id or ""),
        "run_url": run_url or summary.get("run_url", ""),
        **{k: summary.get(k) for k in FIELDS},
        "errors": u.get("error", 0), "warnings": u.get("warning", 0), "info": u.get("info", 0),
        "by_rule": summary.get("by_rule", {}),
    }


def append(collected, out_file, workflow, run_id="", run_url=""):
    rows = []
    for path in sorted(glob.glob(os.path.join(collected, "report-*", "summary.json"))):
        with open(path, encoding="utf-8") as f:
            rows.append(record(json.load(f), workflow, run_id, run_url))
    if rows:
        os.makedirs(os.path.dirname(os.path.abspath(out_file)), exist_ok=True)
        with open(out_file, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return rows


def legacy_csv(path):
    """Старый формат history/<сайт>.csv (до 11.2026) → те же записи."""
    site = os.path.splitext(os.path.basename(path))[0]
    out = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            fixed = {"date", "run", "pages", "pages_failed", "urls", "errors", "warnings", "info", "failed"}
            out.append({
                "workflow": "content", "site": site, "page": None, "started_at": row["date"], "run_id": row["run"],
                "run_url": "", "pages": int(row["pages"]), "pages_failed": int(row["pages_failed"]),
                "urls_checked": int(row["urls"]), "duration_s": None, "failed": row["failed"] == "true",
                "rules_failed": None, "rules_total": None,
                "errors": int(row["errors"]), "warnings": int(row["warnings"]), "info": int(row["info"]),
                "by_rule": {k: int(v) for k, v in row.items() if k not in fixed and v != ""},
            })
    return out


def load(history_dir):
    """Все прогоны: runs.jsonl + старые CSV; повторы (тот же прогон и сайт) отбрасываются."""
    rows = []
    for path in sorted(glob.glob(os.path.join(history_dir, "*.csv"))):
        rows += legacy_csv(path)
    jsonl = os.path.join(history_dir, "runs.jsonl")
    if os.path.exists(jsonl):
        with open(jsonl, encoding="utf-8") as f:
            rows += [json.loads(line) for line in f if line.strip()]
    seen, out = set(), []
    for r in rows:
        key = (r["workflow"], r["site"], r.get("page"), r["run_id"] or r["started_at"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return sorted(out, key=lambda r: r["started_at"])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("append", help="дописать прогон из collected/report-*/summary.json")
    a.add_argument("collected")
    a.add_argument("out_file")
    a.add_argument("--workflow", required=True, choices=["content", "design", "frontend", "backend", "integrations"])
    a.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    a.add_argument("--run-url", default=os.environ.get("RUN_URL", ""))
    args = ap.parse_args()
    rows = append(args.collected, args.out_file, args.workflow, args.run_id, args.run_url)
    print(f"в историю: {len(rows)} строк ({', '.join(r['site'] + (' · ' + r['page'] if r['page'] else '') for r in rows)})",
          file=sys.stderr)


if __name__ == "__main__":
    main()

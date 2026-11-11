#!/usr/bin/env python3
"""Дашборд метрик: одна страница с графиками — качество сайтов, задачи, пайплайны.

    GITHUB_TOKEN=… python checks/core/dashboard.py --history m/history --repo owner/name --out site/

Данные: история прогонов (ветка metrics, checks/core/history.py) и GitHub API — issues, milestones,
прогоны Actions. Без токена (локально) — только история, разделы задач и пайплайнов пустые.
"""
import argparse
import datetime as dt
import json
import os
import statistics
import sys
import urllib.request
from collections import Counter, defaultdict

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)
from checks.core import history  # noqa: E402

API = "https://api.github.com"
CHECK_WORKFLOWS = {"Common checks", "Design checks"}
WORK_LABELS = ["site-fix", "design", "coverage", "autotest", "enhancement", "dependencies"]
SLA_DAYS = {"site-fix": 14}          # задача с этой меткой старше N дней — просрочена
WEEKS = 12
RUN_DAYS = 30


def now():
    return dt.datetime.now(dt.timezone.utc)


def parse(ts):
    if not ts:
        return None
    ts = ts.replace(" UTC", "+00:00").replace("Z", "+00:00")
    if "T" not in ts:
        ts = ts.replace(" ", "T", 1)
    return dt.datetime.fromisoformat(ts)


def gh(path, token):
    req = urllib.request.Request(API + path, headers={"Authorization": f"Bearer {token}",
                                                      "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def gh_all(path, token, key=None, limit=None):
    out, page = [], 1
    while limit is None or len(out) < limit:
        sep = "&" if "?" in path else "?"
        data = gh(f"{path}{sep}per_page=100&page={page}", token)
        items = data[key] if key else data
        out += items
        if len(items) < 100:
            break
        page += 1
    return out[:limit]


def fetch_github(repo, token):
    issues = [i for i in gh_all(f"/repos/{repo}/issues?state=all", token) if "pull_request" not in i]
    milestones = gh_all(f"/repos/{repo}/milestones?state=all", token)
    since = (now() - dt.timedelta(days=RUN_DAYS)).date().isoformat()
    runs = gh_all(f"/repos/{repo}/actions/runs?created=%3E%3D{since}", token, key="workflow_runs")
    for r in runs:  # почему упал прогон проверок: дефекты сайта или инфраструктура
        r["reason"] = None
        if r.get("name") in CHECK_WORKFLOWS and r.get("conclusion") == "failure":
            jobs = gh_all(f"/repos/{repo}/actions/runs/{r['id']}/jobs", token, key="jobs")
            r["reason"] = failure_reason(jobs)
    return issues, milestones, runs


def failure_reason(jobs):
    """«defects» — упали только шаги «Тест: …» (нашли дефекты сайта), иначе «infra» (обход, браузер, сборщик)."""
    failed = [s["name"] for j in jobs for s in j.get("steps", []) if s.get("conclusion") == "failure"]
    return "defects" if failed and all(n.startswith("Тест:") for n in failed) else "infra"


def week_start(d):
    d = d.astimezone(dt.timezone.utc)
    return (d - dt.timedelta(days=d.weekday())).date()


def issues_metrics(issues, today=None):
    today = today or now()
    weeks = [week_start(today) - dt.timedelta(weeks=i) for i in range(WEEKS - 1, -1, -1)]
    opened, closed = Counter(), Counter()
    for i in issues:
        opened[week_start(parse(i["created_at"]))] += 1
        if i.get("closed_at"):
            closed[week_start(parse(i["closed_at"]))] += 1
    open_at = []
    for w in weeks:
        end = dt.datetime.combine(w + dt.timedelta(days=7), dt.time(), dt.timezone.utc)
        open_at.append(sum(1 for i in issues if parse(i["created_at"]) < end
                           and (not i.get("closed_at") or parse(i["closed_at"]) >= end)))
    labels = defaultdict(lambda: {"open": 0, "closed": 0})
    for i in issues:
        for name in (lb["name"] for lb in i.get("labels", [])):
            if name in WORK_LABELS or name.startswith("site:"):
                labels[name]["open" if i["state"] == "open" else "closed"] += 1
    close_days = [(parse(i["closed_at"]) - parse(i["created_at"])).total_seconds() / 86400
                  for i in issues if i.get("closed_at")]
    open_issues = []
    for i in sorted((i for i in issues if i["state"] == "open"), key=lambda i: i["created_at"]):
        names = [lb["name"] for lb in i.get("labels", [])]
        age = (today - parse(i["created_at"])).days
        overdue = any(age > d for lbl, d in SLA_DAYS.items() if lbl in names)
        open_issues.append({"number": i["number"], "title": i["title"], "url": i["html_url"], "age": age,
                            "labels": names, "overdue": overdue})
    return {
        "weeks": [w.isoformat() for w in weeks],
        "opened": [opened[w] for w in weeks], "closed": [closed[w] for w in weeks], "open_at": open_at,
        "labels": dict(sorted(labels.items())),
        "total_open": sum(1 for i in issues if i["state"] == "open"),
        "closed_7d": sum(1 for i in issues if i.get("closed_at") and (today - parse(i["closed_at"])).days < 7),
        "opened_7d": sum(1 for i in issues if (today - parse(i["created_at"])).days < 7),
        "median_close_days": round(statistics.median(close_days), 1) if close_days else None,
        "overdue": sum(1 for o in open_issues if o["overdue"]),
        "oldest": open_issues[:12],
    }


def workflow_name(run):
    """Прогоны Dependabot называются «pip in /. - Update #…» — сводим в одну строку."""
    name = run.get("name") or ""
    return "Dependabot" if " in /" in name and "Update #" in name else name


def runs_metrics(runs, today=None, days=RUN_DAYS):
    today = today or now()
    since = today - dt.timedelta(days=days)
    out = defaultdict(lambda: {"success": 0, "defects": 0, "infra": 0, "other": 0, "durations": []})
    for r in runs:
        start = parse(r.get("run_started_at") or r["created_at"])
        if start < since or r.get("status") != "completed":
            continue
        o = out[workflow_name(r)]
        c = r.get("conclusion")
        if c == "success":
            o["success"] += 1
        elif c == "failure" and r.get("reason"):
            o[r["reason"]] += 1
        elif c == "failure":
            o["infra"] += 1
        else:
            o["other"] += 1  # отменён, ждал подтверждения, пропущен
        if c in ("success", "failure"):
            o["durations"].append((parse(r["updated_at"]) - start).total_seconds() / 60)
    result = {}
    for name, o in sorted(out.items()):
        d = o.pop("durations")
        result[name] = {**o, "median_min": round(statistics.median(d), 1) if d else None}
    recent = [{"name": workflow_name(r), "title": r.get("display_title", ""), "url": r["html_url"],
               "conclusion": r.get("conclusion") or r.get("status"), "reason": r.get("reason"),
               "at": r["created_at"][:16].replace("T", " ")}
              for r in runs[:15]]
    return {"by_workflow": result, "recent": recent, "days": days}


def quality_metrics(rows):
    """Динамика дефектов по сайтам (контент) и страницам (макет), правила последних прогонов."""
    series = defaultdict(list)
    for r in rows:
        name = r["site"] + (f" · {r['page']}" if r.get("page") else "")
        series[(r["workflow"], name)].append(r)
    out = []
    for (workflow, name), rs in sorted(series.items()):
        last = rs[-1]
        recent = rs[-8:]
        rules = sorted({k for r in recent for k, v in r["by_rule"].items() if v})
        out.append({
            "workflow": workflow, "name": name,
            "dates": [r["started_at"][:16] for r in rs],
            "defects": [r["errors"] + r["warnings"] for r in rs],
            "errors": [r["errors"] for r in rs],
            "pages": [r["pages"] for r in rs],
            "last": {"at": last["started_at"], "failed": last["failed"], "errors": last["errors"],
                     "warnings": last["warnings"], "info": last["info"], "pages": last["pages"],
                     "run_url": last.get("run_url", "")},
            "heat": {"runs": [r["started_at"][:10] for r in recent],
                     "rules": [{"rule": k, "counts": [r["by_rule"].get(k, 0) for r in recent]} for k in rules]},
        })
    return out


def milestones_metrics(milestones):
    return [{"title": m["title"], "open": m["open_issues"], "closed": m["closed_issues"], "url": m["html_url"],
             "due": (m.get("due_on") or "")[:10]} for m in milestones]


def build(history_dir, repo=None, token=None):
    rows = history.load(history_dir) if history_dir and os.path.isdir(history_dir) else []
    issues, milestones, runs = fetch_github(repo, token) if repo and token else ([], [], [])
    return {
        "generated_at": now().strftime("%Y-%m-%d %H:%M UTC"),
        "repo": repo or "",
        "quality": quality_metrics(rows),
        "issues": issues_metrics(issues) if issues else None,
        "milestones": milestones_metrics(milestones),
        "runs": runs_metrics(runs) if runs else None,
    }


def summary_md(data):
    """Ключевые цифры для сводки прогона — видны и без Pages."""
    lines = ["## Метрики автотестов", ""]
    i, r = data.get("issues"), data.get("runs")
    if i:
        lines.append(f"- Задач открыто: **{i['total_open']}**, за 7 дней +{i['opened_7d']} / −{i['closed_7d']}, "
                     f"медиана до закрытия: {i['median_close_days'] if i['median_close_days'] is not None else '—'} дн., "
                     f"просрочено site-fix: {i['overdue']}")
    if r:
        for name, w in r["by_workflow"].items():
            lines.append(f"- {name} за {r['days']} дн.: зелёных {w['success']}, дефекты сайта {w['defects']}, "
                         f"инфраструктура {w['infra']}, отменены {w['other']}")
    for q in data.get("quality", []):
        last = q["last"]
        lines.append(f"- {q['name']} ({q['workflow']}): последний прогон {last['at'][:16]} — критичных {last['errors']}, "
                     f"дефектов {last['warnings']}, рекомендаций {last['info']}")
    if len(lines) == 2:
        lines.append("Данных пока нет.")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--history", help="папка history из ветки metrics")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    ap.add_argument("--out", default="site")
    ap.add_argument("--summary", metavar="DATA_JSON", help="только напечатать ключевые цифры из готового data.json")
    args = ap.parse_args()
    if args.summary:
        with open(args.summary, encoding="utf-8") as f:
            print(summary_md(json.load(f)), end="")
        return
    data = build(args.history, args.repo, os.environ.get("GITHUB_TOKEN"))
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html"), encoding="utf-8") as f:
        page = f.read().replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    with open(os.path.join(args.out, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)
    q = len(data["quality"])
    print(f"дашборд: {args.out}/index.html — рядов качества {q}, задач "
          f"{data['issues']['total_open'] if data['issues'] else '—'} открыто", file=sys.stderr)


if __name__ == "__main__":
    main()

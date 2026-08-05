"""Per-user-story evidence helpers — screenshots + console dump + result records."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path


def artifacts_root() -> Path:
    root = Path(os.environ.get("SWEEP_ARTIFACTS_DIR", "./_artifacts"))
    root = Path(root)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    out = root / today
    out.mkdir(parents=True, exist_ok=True)
    (out / "screenshots").mkdir(exist_ok=True)
    (out / "console").mkdir(exist_ok=True)
    return out


def screenshot(page, role: str, story: str) -> Path:
    out = artifacts_root() / "screenshots" / role / f"{story}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out), full_page=True)
    return out


def write_console_dump(role: str, story: str, errors: list[dict]) -> Path:
    out = artifacts_root() / "console" / role / f"{story}.log"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "\n".join(f"[{e['kind']}] {e['text']}" for e in errors) + "\n",
        encoding="utf-8",
    )
    return out


def append_result(role: str, story: str, status: str, detail: str = "") -> None:
    """Append a JSON line to the run's sweep-results.jsonl."""
    out = artifacts_root() / "sweep-results.jsonl"
    record = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "role": role,
        "story": story,
        "status": status,
        "detail": detail,
    }
    with out.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def write_role_markdown(role: str, persona: str, results: list[dict]) -> Path:
    """Produce docs/sweep/<date>/role-<role>.md from collected results."""
    out = artifacts_root() / f"role-{role}.md"
    lines = [
        f"# Sweep Evidence — {persona} (`{role}`)",
        "",
        f"_Generated: {datetime.utcnow().isoformat()}Z_",
        "",
        "| Story | Status | Detail |",
        "|---|---|---|",
    ]
    for r in results:
        emoji = "PASS" if r["status"] == "pass" else "FAIL"
        lines.append(f"| {r['story']} | {emoji} | {r.get('detail', '')} |")
    lines.append("")
    failed = [r for r in results if r["status"] != "pass"]
    if failed:
        lines.append("## Failures")
        lines.append("")
        for f in failed:
            lines.append(f"- **{f['story']}** — {f.get('detail', '')}")
            lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def write_summary(all_results: dict[str, list[dict]]) -> Path:
    out = artifacts_root() / "summary.md"
    lines = [
        f"# Sweep Summary — {datetime.utcnow().strftime('%Y-%m-%d')}",
        "",
        f"FC_SITE: `{os.environ.get('FC_SITE', '<unset>')}`",
        "",
        "## Totals",
        "",
    ]
    total_pass = total_fail = 0
    for role, results in all_results.items():
        p = sum(1 for r in results if r["status"] == "pass")
        f = len(results) - p
        total_pass += p
        total_fail += f
        lines.append(f"- **{role}**: {p} pass, {f} fail")
    lines.append("")
    lines.append(f"**Aggregate**: {total_pass} pass, {total_fail} fail.")
    lines.append("")
    if total_fail == 0:
        lines.append("## Verdict")
        lines.append("")
        lines.append("READY — every user-story passed.")
    else:
        lines.append("## Verdict")
        lines.append("")
        lines.append("NOT READY — see per-role docs for failures.")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out

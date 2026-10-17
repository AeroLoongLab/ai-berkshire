#!/usr/bin/env python3
"""Generate DeepSeek Harness (DSH) skills from AI Berkshire Claude command files.

DSH discovers skills only under specific roots (``<project>/.dsh/skills``,
``<project>/.agents/skills``, ``$DSH_HOME/skills``, ``~/.agents/skills``) and
requires YAML front-matter with ``name`` + ``description``. The canonical
workflow files in ``skills/*.md`` are Claude Code slash commands: no
front-matter, ``$ARGUMENTS`` substitution, prose-only. This script adapts them
into project-level DSH skills at ``.dsh/skills/<name>/SKILL.md`` so both
surfaces stay generated from one source of truth.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLAUDE_SKILLS = ROOT / "skills"
DSH_SKILLS = ROOT / ".dsh" / "skills"

DESCRIPTION_LIMIT = 220

# Inline text used where the source relies on Claude Code argument substitution.
ARGUMENTS_PLACEHOLDER = "本轮对话中的标的/参数"


def split_frontmatter(text: str) -> tuple[str | None, str]:
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return None, text
    return text[4:end], text[end + 5 :].lstrip("\n")


def first_heading(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


CJK = "\u2e80-\u9fff\u3000-\u303f\uff00-\uffef"


def squeeze_cjk(text: str, placeholder: str) -> str:
    """Drop spaces between a CJK placeholder and adjacent CJK characters."""

    escaped = re.escape(placeholder)
    text = re.sub(rf"(?<=[{CJK}])\s+(?={escaped})", "", text)
    text = re.sub(rf"(?<={escaped})\s+(?=[{CJK}])", "", text)
    return text


def replace_arguments(text: str, placeholder: str) -> str:
    return squeeze_cjk(text.replace("$ARGUMENTS", placeholder), placeholder)


def clean_paragraph(lines: list[str]) -> str:
    text = " ".join(line.strip() for line in lines)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = text.replace("`", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def first_paragraph(body: str) -> str:
    """Return the first prose paragraph after the H1, or ""."""

    def block(lines: list[str], start: int) -> tuple[list[str], int]:
        collected: list[str] = []
        while start < len(lines):
            line = lines[start].strip()
            if not line:
                break
            if line.startswith("#") or line.startswith("|"):
                return collected, start
            collected.append(line[1:].strip() if line.startswith(">") else line)
            start += 1
        return collected, start

    lines = body.splitlines()
    # Skip leading blank lines and the H1 line.
    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index < len(lines) and lines[index].startswith("# "):
        index += 1
    while index < len(lines) and not lines[index].strip():
        index += 1

    paragraph, index = block(lines, index)
    text = clean_paragraph(paragraph)
    # "Analyze X to answer:" style leads continue in the next block.
    if text.endswith((":", "：")):
        while index < len(lines) and not lines[index].strip():
            index += 1
        followup, _ = block(lines, index)
        if followup:
            text = f"{text} {clean_paragraph(followup)}"
    return text


def truncate(text: str, limit: int = DESCRIPTION_LIMIT) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for separator in ("。", "；", "，", " "):
        position = cut.rfind(separator)
        if position >= limit // 2:
            cut = cut[: position + 1]
            break
    return cut.rstrip("。；， ") + "…"


def frontmatter_description(existing: str | None) -> str | None:
    if not existing:
        return None
    match = re.search(r"(?m)^description:\s*(.+)$", existing)
    if not match:
        return None
    value = match.group(1).strip()
    if value.startswith(("\"", "'")) and value[-1:] == value[0]:
        value = value[1:-1]
    return value or None


def yaml_quote(value: str) -> str:
    value = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{value}"'


def description_placeholder(text: str) -> str:
    """Pick the placeholder that reads naturally inside a description."""

    if sum(1 for char in text if "\u4e00" <= char <= "\u9fff") >= 8:
        return "标的"
    return "the target company"


def metadata(name: str, source_text: str) -> tuple[str, str]:
    existing, body = split_frontmatter(source_text)
    description = frontmatter_description(existing)
    if not description:
        title = first_heading(body, name)
        paragraph = first_paragraph(body)
        if paragraph:
            paragraph = replace_arguments(paragraph, description_placeholder(paragraph))
            description = f"{title}。{paragraph}"
        else:
            description = title
        description = truncate(description)
    header = (
        "---\n"
        f"name: {name}\n"
        f"description: {yaml_quote(description)}\n"
        "---\n\n"
    )
    return header, body


def adapter_note(source_name: str) -> str:
    return (
        "> 本文件由 `scripts/sync-dsh-skills.py` 从 "
        f"`skills/{source_name}` 自动生成，请勿手改；改完源文件后重跑该脚本。\n\n"
        "## DeepSeek Harness 适配说明\n\n"
        f"- 仓库根目录：`{ROOT}`。所有 `tools/...`、`reports/...`、`scripts/...` "
        "路径都相对仓库根目录解析；若当前工作目录不是仓库根目录，"
        "先用 `git rev-parse --show-toplevel` 定位，或直接使用绝对路径。\n"
        "- 本文件**不做 `$ARGUMENTS` 替换**：标的与参数取自本轮对话中用户的表述；"
        f"源文件里的 `$ARGUMENTS` 已改写为“{ARGUMENTS_PLACEHOLDER}”。\n"
        "- 源文件若提到 Claude Code 的 Task / Agent / WebSearch 工具，"
        "在本环境中替换为等价能力：`subagent`（并行子代理）、`web_search` / "
        "`web_fetch`、`bash`、`read` / `write` / `edit`；需要多角色并行时"
        "可用 Agent Teams（`spawn_teammate`）。\n"
        "- 动笔前先跑 `date` 确认今天日期，并把它作为“最新数据”的基准写入报告头部；"
        "报告按 `CLAUDE.md` 的目录与命名规范落到 `reports/` 下。\n"
        "- 涉及财务数据时遵守 `AGENTS.md` 的研究质量规则：关键数据双源交叉验证、"
        "用 `tools/financial_rigor.py` 做精确计算、不确定处明确标注。\n\n"
        "---\n\n"
    )


def build(name: str, source: Path) -> str:
    source_text = source.read_text(encoding="utf-8")
    header, body = metadata(name, source_text)
    body = replace_arguments(body, ARGUMENTS_PLACEHOLDER)
    return header + adapter_note(source.name) + body.rstrip() + "\n"


def main() -> None:
    check = "--check" in sys.argv[1:]
    unknown_args = [arg for arg in sys.argv[1:] if arg != "--check"]
    if unknown_args:
        raise SystemExit("Unknown argument(s): " + ", ".join(unknown_args))

    if not check:
        DSH_SKILLS.mkdir(parents=True, exist_ok=True)

    sources = sorted(CLAUDE_SKILLS.glob("*.md"))
    expected = {source.stem for source in sources}
    stale: list[str] = []

    for source in sources:
        target = DSH_SKILLS / source.stem / "SKILL.md"
        content = build(source.stem, source)
        if check:
            if not target.exists() or target.read_text(encoding="utf-8") != content:
                stale.append(str(target.relative_to(ROOT)))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    if DSH_SKILLS.exists():
        for directory in sorted(DSH_SKILLS.iterdir()):
            if not directory.is_dir() or directory.name in expected:
                continue
            extra = directory / "SKILL.md"
            if not extra.exists():
                continue
            if check:
                stale.append(str(extra.relative_to(ROOT)) + " (source removed)")
            else:
                extra.unlink()
                directory.rmdir()

    relative = DSH_SKILLS.relative_to(ROOT)
    if check:
        if stale:
            print("DSH skills are out of date:")
            for path in stale:
                print(f"  {path}")
            raise SystemExit(1)
        print(f"Checked {len(sources)} DSH skills in {relative}")
        return

    print(f"Generated {len(sources)} DSH skills in {relative}")


if __name__ == "__main__":
    main()

"""Always-on skills management: active_skills.json, extraction, CLI, injection."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import store

ACTIVE_SKILLS_REL = "active_skills.json"
SKILLS_NOTE = (
    "Global skills directory: ~/.agents/skills/ (load full workflow via skill.load or reading SKILL.md)"
)

DEFAULT_CONFIG: Dict[str, Any] = {
    "active_skills": [],
    "intensity": {},
}


def active_skills_path() -> Path:
    return store.USER_MEMORY / ACTIVE_SKILLS_REL


def skills_dir() -> Path:
    raw = os.environ.get("AGENTS_SKILLS_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    default_user_memory = (store.AGENTS_HOME / "memory").resolve()
    try:
        current_user_memory = store.USER_MEMORY.resolve()
    except OSError:
        current_user_memory = store.USER_MEMORY
    if current_user_memory != default_user_memory:
        return store.USER_MEMORY.parent / "skills"
    return store.AGENTS_HOME / "skills"


def load_active_skills_config() -> Dict[str, Any]:
    path = active_skills_path()
    if not path.is_file():
        cfg = {
            "active_skills": list(DEFAULT_CONFIG["active_skills"]),
            "intensity": dict(DEFAULT_CONFIG["intensity"]),
        }
        save_active_skills_config(cfg)
        return cfg
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("active_skills.json must be a JSON object")
        if "active_skills" not in data or not isinstance(data["active_skills"], list):
            data["active_skills"] = list(DEFAULT_CONFIG["active_skills"])
        if "intensity" not in data or not isinstance(data["intensity"], dict):
            data["intensity"] = dict(DEFAULT_CONFIG["intensity"])
        return data
    except Exception:
        cfg = {
            "active_skills": list(DEFAULT_CONFIG["active_skills"]),
            "intensity": dict(DEFAULT_CONFIG["intensity"]),
        }
        save_active_skills_config(cfg)
        return cfg


def save_active_skills_config(cfg: Dict[str, Any]) -> None:
    path = active_skills_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


def list_installed_skills() -> List[str]:
    sdir = skills_dir()
    if not sdir.is_dir():
        return []
    skills: List[str] = []
    for item in sorted(sdir.iterdir()):
        if item.is_dir() and (item / "SKILL.md").is_file():
            skills.append(item.name)
    return skills


def parse_skill_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """Parse YAML frontmatter and markdown body from SKILL.md without third-party deps."""
    frontmatter: Dict[str, Any] = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            fm_text = parts[1]
            body = parts[2]
            cur_key: Optional[str] = None
            cur_parent: Optional[str] = None
            for line in fm_text.splitlines():
                line_str = line.rstrip()
                if not line_str.strip() or line_str.strip().startswith("#"):
                    continue
                # Indented child key under a dict, e.g. "  ultra: ..."
                if line_str.startswith("  ") and ":" in line_str and cur_parent:
                    k, v = line_str.strip().split(":", 1)
                    k = k.strip()
                    v = v.strip().strip("\"'")
                    if not isinstance(frontmatter.get(cur_parent), dict):
                        frontmatter[cur_parent] = {}
                    frontmatter[cur_parent][k] = v
                    cur_key = k
                    continue
                # Indented list item, e.g. "  - item"
                if line_str.strip().startswith("- ") and cur_parent:
                    val = line_str.strip()[2:].strip().strip("\"'")
                    if not isinstance(frontmatter.get(cur_parent), list):
                        frontmatter[cur_parent] = []
                    frontmatter[cur_parent].append(val)
                    continue
                # Top level key
                if ":" in line_str:
                    k, v = line_str.split(":", 1)
                    k = k.strip()
                    v = v.strip().strip("\"'")
                    cur_parent = k
                    cur_key = k
                    if v == ">" or v == "|":
                        frontmatter[k] = ""
                    elif v:
                        frontmatter[k] = v
                    else:
                        frontmatter[k] = {}
                elif cur_key and line_str.startswith(" "):
                    # Multi-line string continuation (e.g. description: >)
                    val = line_str.strip().strip("\"'")
                    if isinstance(frontmatter.get(cur_key), str):
                        prev = frontmatter[cur_key]
                        frontmatter[cur_key] = f"{prev} {val}".strip() if prev else val
    return frontmatter, body


def extract_skill_rules(name: str, skill_file: Path, intensity: str = "full") -> List[str]:
    """Extract durable hard rules from a skill definition (SKILL.md)."""
    try:
        text = skill_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    fm, body = parse_skill_frontmatter(text)

    # 1. Frontmatter always_on_rule / always_on_rules
    rule_entry = fm.get("always_on_rule") or fm.get("always_on_rules")
    if rule_entry:
        if isinstance(rule_entry, dict):
            matched = (
                rule_entry.get(intensity)
                or rule_entry.get("full")
                or rule_entry.get("default")
                or (next(iter(rule_entry.values())) if rule_entry else "")
            )
            if matched:
                return [matched.strip()]
        elif isinstance(rule_entry, list):
            return [str(r).strip() for r in rule_entry if str(r).strip()]
        elif isinstance(rule_entry, str) and rule_entry.strip():
            return [rule_entry.strip()]

    # 2. Frontmatter rules list
    fm_rules = fm.get("rules")
    if isinstance(fm_rules, list):
        extracted = [str(r).strip() for r in fm_rules if str(r).strip()]
        if extracted:
            return extracted

    # 3. Section in body: ## Always-On Rule(s) or ## Rules
    rule_section_re = re.compile(
        r"^##\s+(?:Always-On Rules?|Hard Rules?|Rules)\s*$", re.IGNORECASE | re.MULTILINE
    )
    m = rule_section_re.search(body)
    if m:
        after = body[m.end() :]
        next_heading = re.search(r"^##\s+", after, re.MULTILINE)
        section_text = after[: next_heading.start()] if next_heading else after
        bullets = []
        for line in section_text.splitlines():
            s = line.strip()
            if s.startswith("- ") or s.startswith("* "):
                bullet = s[2:].strip()
                if bullet:
                    bullets.append(bullet)
        if bullets:
            return bullets

    # 4. Fallback: description frontmatter
    desc = fm.get("description")
    if isinstance(desc, str) and desc.strip():
        first = desc.strip().split("\n")[0].strip()
        return [f"{name}: {first}"]

    return [f"{name}: active skill"]


def get_active_skills_rules() -> List[str]:
    cfg = load_active_skills_config()
    active = cfg.get("active_skills") or []
    intensities = cfg.get("intensity") or {}
    sdir = skills_dir()

    rules: List[str] = []
    for name in active:
        skill_file = sdir / name / "SKILL.md"
        if not skill_file.is_file():
            continue
        level = intensities.get(name, "full")
        rules.extend(extract_skill_rules(name, skill_file, level))
    return rules


def enable_skill(name: str, intensity: Optional[str] = None) -> Dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("Skill name cannot be empty")
    cfg = load_active_skills_config()
    active = cfg.setdefault("active_skills", [])
    intensities = cfg.setdefault("intensity", {})
    if name not in active:
        active.append(name)
    if intensity:
        intensities[name] = intensity.strip()
    elif name not in intensities:
        intensities[name] = "full"
    save_active_skills_config(cfg)
    return cfg


def disable_skill(name: str) -> Dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("Skill name cannot be empty")
    cfg = load_active_skills_config()
    active = cfg.setdefault("active_skills", [])
    if name in active:
        active.remove(name)
    save_active_skills_config(cfg)
    return cfg


def build_skills_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agents_memory skills",
        description="Manage active always-on agent skills (list, enable, disable).",
    )
    sub = parser.add_subparsers(dest="action")

    list_p = sub.add_parser("list", help="List all skills in ~/.agents/skills/ with active status")
    list_p.add_argument("--json", action="store_true", help="Output JSON")

    enable_p = sub.add_parser("enable", help="Add skill to active_skills.json")
    enable_p.add_argument("name", help="Skill name (e.g. review, format)")
    enable_p.add_argument("--intensity", "-i", default="", help="Intensity level (e.g. ultra, full, lite)")

    disable_p = sub.add_parser("disable", help="Remove skill from active_skills.json")
    disable_p.add_argument("name", help="Skill name (e.g. review, format)")
    return parser


def skills_list_cmd(as_json: bool = False) -> int:
    cfg = load_active_skills_config()
    active = cfg.get("active_skills") or []
    intensities = cfg.get("intensity") or {}
    installed = list_installed_skills()
    all_names = sorted(set(installed) | set(active))
    if as_json:
        result = []
        for name in all_names:
            is_act = name in active
            level = intensities.get(name, "full") if is_act else None
            result.append({
                "name": name,
                "active": is_act,
                "intensity": level,
                "installed": name in installed,
            })
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if not all_names:
        print("No skills found in ~/.agents/skills/")
        return 0
    for name in all_names:
        if name in active:
            level = intensities.get(name, "full")
            note = "" if name in installed else " [not installed]"
            print(f"{name}: active (intensity: {level}){note}")
        else:
            print(f"{name}: inactive")
    return 0


def skills_enable_cmd(name: str, intensity: str = "") -> int:
    name = (name or "").strip()
    if not name:
        print("Error: skill name required", file=sys.stderr)
        return 2
    cfg = enable_skill(name, intensity=intensity if intensity else None)
    level = cfg.get("intensity", {}).get(name, "full")
    sdir = skills_dir()
    if not (sdir / name / "SKILL.md").is_file():
        print(f"Enabled skill '{name}' (intensity: {level}) [Note: {name}/SKILL.md not found in {sdir}]")
    else:
        print(f"Enabled skill '{name}' (intensity: {level})")
    return 0


def skills_disable_cmd(name: str) -> int:
    name = (name or "").strip()
    if not name:
        print("Error: skill name required", file=sys.stderr)
        return 2
    disable_skill(name)
    print(f"Disabled skill '{name}'")
    return 0


def skills_main(argv: Optional[List[str]] = None) -> int:
    parser = build_skills_parser()
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        parser.print_help()
        return 0
    parsed = parser.parse_args(args)
    if parsed.action == "list":
        return skills_list_cmd(as_json=getattr(parsed, "json", False))
    elif parsed.action == "enable":
        return skills_enable_cmd(parsed.name, parsed.intensity)
    elif parsed.action == "disable":
        return skills_disable_cmd(parsed.name)
    parser.print_help()
    return 0

"""A stand-in for the few `openclaw` commands claw_skills_kit.integrations uses. Test-only.

Usage: python fake_openclaw.py STATE_DIR <openclaw args...>
STATE_DIR holds openclaw.json and skills/. Two switch files force failures:
  STATE_DIR/invalid      -> `config validate` exits 1
  STATE_DIR/never_ready  -> `skills check` never lists a skill as eligible
Eligibility mirrors OpenClaw's rule: every requires.env variable is in the process env or in
skills.entries.<skill>.env, or is the primaryEnv and the entry has an apiKey.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from claw_skills_kit.integrations import read_requirements  # noqa: E402


def load(state):
    path = state / "openclaw.json"
    return json.loads(path.read_text()) if path.exists() else {}


def save(state, data):
    (state / "openclaw.json").write_text(json.dumps(data, indent=2))


def main(argv):
    state, args = Path(argv[0]), argv[1:]
    data = load(state)
    if args[:2] == ["config", "file"]:
        print(state / "openclaw.json")
        return 0
    if args[:2] == ["config", "set"] and args[2] == "--batch-json":
        for item in json.loads(args[3]):
            *parents, last = item["path"].split(".")
            node = data
            for key in parents:
                node = node.setdefault(key, {})
            node[last] = item["value"]
        save(state, data)
        return 0
    if args[:2] == ["config", "unset"]:
        *parents, last = args[2].split(".")
        node = data
        for key in parents:
            node = node.get(key, {})
        node.pop(last, None)
        save(state, data)
        return 0
    if args[:2] == ["config", "validate"]:
        return 1 if (state / "invalid").exists() else 0
    if args[:3] == ["skills", "check", "--json"]:
        entries = (data.get("skills") or {}).get("entries") or {}
        eligible, missing = [], []
        for skill_md in sorted((state / "skills").glob("*/SKILL.md")):
            name = skill_md.parent.name
            req = read_requirements(skill_md.read_text())
            entry = entries.get(name) or {}
            have = set(os.environ) | set(entry.get("env") or {})
            if req.primary_env and isinstance(entry.get("apiKey"), dict):
                have.add(req.primary_env)
            lacking = [n for n in req.env if n not in have]
            if entry.get("enabled") is False:
                continue  # listed as disabled by the real openclaw, never eligible
            if lacking or (state / "never_ready").exists():
                missing.append({"name": name, "missing": {"env": lacking}})
            else:
                eligible.append(name)
        print(json.dumps({"eligible": eligible, "missingRequirements": missing}))
        return 0
    print(f"fake openclaw: unsupported {args}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Install the purge contract as a Doubao skill pack + local workspace files.

Standard library only. Idempotent. Keeps a manifest so --uninstall removes
exactly (and only) the files this script generated.

    python install.py                     # install
    python install.py --dry-run           # show what would be written
    python install.py --data-dir PATH     # explicit Doubao workspace path
    python install.py --home PATH         # explicit ~/Doubao equivalent
    python install.py --uninstall         # remove generated files
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"
WS_TEMPLATES = HERE / "workspace"
MANIFEST_NAME = ".purge-port-manifest.json"


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_src(name):
    p = SRC / name
    if not p.is_file():
        raise SystemExit("missing source file: %s" % p)
    return p.read_text(encoding="utf-8")


def detect_workspace(explicit):
    candidates = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Doubao" / "User Data" / "Default" /
                          ".doubao" / "agent_mode" / "workspace")
    home = Path.home()
    candidates += [
        home / "Library" / "Application Support" / "Doubao" / "User Data" / "Default" /
        ".doubao" / "agent_mode" / "workspace",
        home / ".config" / "Doubao" / "User Data" / "Default" /
        ".doubao" / "agent_mode" / "workspace",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return None


def render(template_name, doubao_home):
    text = (WS_TEMPLATES / template_name).read_text(encoding="utf-8")
    return text.replace("<DOUBAO_HOME>", str(doubao_home))


def build_plan(workspace, doubao_home, no_workspace):
    def localize(text):
        return text.replace("<DOUBAO_HOME>", str(doubao_home))

    skill = localize(read_src("SKILL.md"))
    contract = localize(read_src("contract.md"))
    pref = localize(read_src("preference-instruction.txt"))

    plan = {}
    if workspace is not None:
        # Primary load root: the one Doubao actually scans.
        base = workspace / ".user_skills" / "purge-contract"
        plan[base / "SKILL.md"] = skill
        plan[base / "references" / "contract.md"] = contract

    # Secondary load root, plus workspace navigation files.
    plan[doubao_home / "skills" / "purge-contract" / "SKILL.md"] = skill
    if not no_workspace:
        plan[doubao_home / "PURGE.md"] = contract
        plan[doubao_home / "AGENTS.md"] = render("AGENTS.md", doubao_home)
        plan[doubao_home / "README.md"] = render("README.md", doubao_home)
        plan[doubao_home / "preference-instruction.txt"] = pref
    return plan


def do_install(args):
    workspace = detect_workspace(args.data_dir)
    doubao_home = Path(args.home).expanduser() if args.home else Path.home() / "Doubao"
    plan = build_plan(workspace, doubao_home, args.no_workspace)

    print("Doubao workspace : %s" % (workspace if workspace else "NOT FOUND (use --data-dir)"))
    print("Local home       : %s" % doubao_home)
    print("Files to write   : %d" % len(plan))
    print("-" * 72)

    if args.dry_run:
        for path, text in plan.items():
            print("  [%s] %s  (%d chars)" % ("new" if not path.is_file() else "overwrite",
                                             path, len(text)))
        print("\nDRY RUN - nothing written.")
        return 0

    written = {}
    for path, text in plan.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written[str(path)] = sha(text)
        print("  WROTE %s (%d chars)" % (path, len(text)))

    manifest = doubao_home / MANIFEST_NAME
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({
        "generator": "doubao-purge-port/install.py",
        "workspace": str(workspace) if workspace else None,
        "doubao_home": str(doubao_home),
        "files": written,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("  WROTE %s" % manifest)

    print("\n" + "=" * 72)
    print("NEXT: the skill pack is on disk, but per-turn injection is a separate step.")
    print("  A) automatic : python inject_preference.py")
    print("  B) manual    : Settings -> Work Mode Settings -> Personalization")
    print("                 -> 工作任务偏好指令 -> paste the FULL text of")
    print("                 %s" % (doubao_home / "preference-instruction.txt"))
    print("                 (3744 chars, textarea limit is 10000), then Save.")
    print("Then restart Doubao, switch to 工作任务 mode, and run:")
    print("  python verify/verify_behavior.py")
    print("=" * 72)
    if workspace is None:
        print("\nNOTE: Doubao data dir was not auto-detected. Re-run with --data-dir")
        print("      pointing at the agent_mode/workspace directory; other files")
        print("      were still written to the local home.")
    return 0


def do_uninstall(args):
    doubao_home = Path(args.home).expanduser() if args.home else Path.home() / "Doubao"
    manifest = doubao_home / MANIFEST_NAME
    if not manifest.is_file():
        print("No manifest at %s - nothing to uninstall." % manifest)
        return 0
    data = json.loads(manifest.read_text(encoding="utf-8"))
    removed, kept = 0, 0
    for raw, expected in data.get("files", {}).items():
        p = Path(raw)
        if not p.is_file():
            continue
        actual = sha(p.read_text(encoding="utf-8"))
        if actual != expected:
            print("  KEPT (modified by user): %s" % p)
            kept += 1
            continue
        p.unlink()
        print("  REMOVED %s" % p)
        removed += 1
    manifest.unlink()
    print("Removed %d file(s), kept %d modified file(s), manifest deleted." % (removed, kept))
    print("The 工作任务偏好指令 is account-level: clear it manually in Settings.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", help="Doubao agent_mode/workspace directory")
    ap.add_argument("--home", help="local Doubao workspace root (default ~/Doubao)")
    ap.add_argument("--dry-run", action="store_true", help="show planned writes only")
    ap.add_argument("--no-workspace", action="store_true",
                    help="skip PURGE.md / AGENTS.md / README.md / preference backup")
    ap.add_argument("--uninstall", action="store_true", help="remove generated files")
    args = ap.parse_args()
    return do_uninstall(args) if args.uninstall else do_install(args)


if __name__ == "__main__":
    sys.exit(main())

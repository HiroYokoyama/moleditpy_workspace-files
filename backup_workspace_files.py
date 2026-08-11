"""Back the DEV_MAIN workspace files up into the moleditpy_workspace-files repo.

Copies an allowlist of paths -- the root scripts and docs, plus the Claude agents
and skills -- into the backup checkout, then commits there. Nothing else in
DEV_MAIN is read or touched: the plugin repos, note/, other/ and every scratch
directory are outside the allowlist by construction.

  python G:/DEV_MAIN/backup_workspace_files.py            # copy + commit
  python G:/DEV_MAIN/backup_workspace_files.py --push     # ... and push
  python G:/DEV_MAIN/backup_workspace_files.py --dry-run  # show what would change
  python G:/DEV_MAIN/backup_workspace_files.py --prune    # also drop stale copies
"""

import argparse
import filecmp
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(ROOT, "moleditpy_workspace-files")

# (source path relative to DEV_MAIN, destination relative to the backup repo).
# A directory source copies its whole tree; the destination keeps that structure.
ALLOWLIST = [
    ("CLAUDE.md", "CLAUDE.md"),
    ("README.md", "README.md"),
    ("check_wiki_versions.py", "check_wiki_versions.py"),
    ("backup_workspace_files.py", "backup_workspace_files.py"),
    ("run_all", "run_all"),
    ("run_all.bat", "run_all.bat"),
    ("run_all.ps1", "run_all.ps1"),
    ("run_all_tests.py", "run_all_tests.py"),
    ("roll_registry_pat.bat", "roll_registry_pat.bat"),
    ("roll_registry_pat.ps1", "roll_registry_pat.ps1"),
    ("roll_registry_pat.py", "roll_registry_pat.py"),
    ("roll_zenodo_token.ps1", "roll_zenodo_token.ps1"),
    ("roll_zenodo_token.py", "roll_zenodo_token.py"),
    (".claude/agents", "agents"),
    (".claude/skills", "skills"),
]

# Machine-local or generated files that must never leave this machine.
SKIP_NAMES = {"settings.local.json", ".DS_Store", "Thumbs.db"}
SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache", ".ruff_cache"}


def pairs():
    """Every (source file, destination file) the allowlist expands to."""
    for source, destination in ALLOWLIST:
        absolute = os.path.join(ROOT, source)
        if os.path.isfile(absolute):
            yield absolute, os.path.join(BACKUP, destination)
        elif os.path.isdir(absolute):
            for base, dirs, files in os.walk(absolute):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for name in sorted(files):
                    if name in SKIP_NAMES:
                        continue
                    relative = os.path.relpath(os.path.join(base, name), absolute)
                    yield (os.path.join(base, name),
                           os.path.join(BACKUP, destination, relative))
        else:
            print("missing, skipped: %s" % source)


def git(*args, **kwargs):
    return subprocess.run(("git", "-C", BACKUP) + args, check=True, text=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--push", action="store_true", help="push after committing")
    parser.add_argument("--dry-run", action="store_true", help="report, change nothing")
    parser.add_argument("--prune", action="store_true",
                        help="delete backup files no longer in the allowlist")
    args = parser.parse_args()

    if not os.path.isdir(os.path.join(BACKUP, ".git")):
        sys.exit("no backup checkout at %s" % BACKUP)

    copied, kept = [], set()
    for source, destination in pairs():
        relative = os.path.relpath(destination, BACKUP).replace("\\", "/")
        kept.add(relative)
        # shallow=False: same size and mtime is not proof for hand-edited text.
        if os.path.isfile(destination) and filecmp.cmp(source, destination, shallow=False):
            continue
        copied.append(relative)
        if not args.dry_run:
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.copy2(source, destination)

    tracked = git("ls-files", capture_output=True).stdout.split()
    stale = sorted(set(tracked) - kept)
    if stale and args.prune and not args.dry_run:
        git("rm", "--quiet", *stale)
    for path in stale:
        print(("pruned: %s" if args.prune else "in backup only, left alone: %s") % path)

    for path in copied:
        print("updated: %s" % path)
    if args.dry_run:
        print("dry run: %d file(s) would change" % len(copied))
        return 0
    if not git("status", "--porcelain", capture_output=True).stdout.strip():
        print("backup already up to date")
        return 0

    git("add", "-A")
    git("commit", "--quiet", "-m", "Back up workspace files (%d changed)" % len(copied))
    print("committed %d file(s)" % len(copied))
    if args.push:
        git("push")
        print("pushed")
    else:
        print("not pushed; re-run with --push when you want it published")
    return 0


if __name__ == "__main__":
    sys.exit(main())

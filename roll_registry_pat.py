#!/usr/bin/env python3
"""
roll_registry_pat.py

Interactive script to rotate/update the `REGISTRY_PAT` GitHub secret across
all MoleditPy plugin repositories in DEV_MAIN.

Uses getpass for secure (hidden) PAT entry and gh CLI for secret updates.

Security notes:
  - Token is passed to `gh secret set` via stdin (never via command-line args).
  - Token memory is overwritten with zeros after use (best-effort; Python
    strings are immutable, but we zero the bytearray copy used for stdin).
  - Repository names are validated against a strict allowlist pattern before
    being passed to subprocess to prevent command injection.
"""

import sys
import os
import re
import glob
import subprocess
import getpass

DEFAULT_OWNER = "HiroYokoyama"
SECRET_NAME = "REGISTRY_PAT"

# Strict pattern: only allow alphanumeric, hyphens, underscores, and dots
# (standard GitHub repository name characters). This prevents directory
# traversal or shell metacharacter injection via crafted folder names.
_SAFE_REPO_NAME = re.compile(r"^[A-Za-z0-9._-]+$")

# GitHub PAT prefixes (classic and fine-grained)
_VALID_PAT_PREFIXES = ("ghp_", "github_pat_", "gho_")


def check_gh_cli():
    """Verify that gh CLI is installed and authenticated."""
    try:
        res = subprocess.run(
            ["gh", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        if res.returncode != 0:
            print("[ERROR] GitHub CLI ('gh') is not installed or not in PATH.")
            sys.exit(1)
    except FileNotFoundError:
        print("[ERROR] GitHub CLI ('gh') is not installed or not in PATH.")
        sys.exit(1)

    res = subprocess.run(
        ["gh", "auth", "status"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    if res.returncode != 0:
        print("[ERROR] GitHub CLI is not authenticated. Run 'gh auth login' first.")
        # Print only the first line of stderr to avoid leaking token fragments.
        first_line = (res.stderr or res.stdout or "").split("\n", 1)[0]
        if first_line:
            print(f"  Detail: {first_line}")
        sys.exit(1)


def discover_repositories(dev_main_dir=None):
    """Find all local repos in dev_main_dir whose workflows reference REGISTRY_PAT."""
    if not dev_main_dir:
        dev_main_dir = os.path.dirname(os.path.abspath(__file__))

    repos = set()
    patterns = [
        os.path.join(dev_main_dir, "*", ".github", "workflows", "*.yml"),
        os.path.join(dev_main_dir, "*", ".github", "workflows", "*.yaml"),
    ]

    for pattern in patterns:
        for filepath in glob.glob(pattern):
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    if SECRET_NAME in f.read():
                        repo_dir = os.path.basename(
                            os.path.dirname(os.path.dirname(os.path.dirname(filepath)))
                        )
                        # Validate the directory name before accepting it.
                        if _SAFE_REPO_NAME.match(repo_dir):
                            repos.add(repo_dir)
                        else:
                            print(
                                f"[WARN] Skipping directory with unsafe name: {repo_dir!r}"
                            )
            except OSError as exc:
                print(f"[WARN] Could not read {filepath}: {exc}")

    return sorted(list(repos))


def _zero_bytearray(ba: bytearray) -> None:
    """Best-effort zeroing of a bytearray to reduce secret residue in memory."""
    for i in range(len(ba)):
        ba[i] = 0


def main():
    print("=" * 60)
    print("  MoleditPy Plugin Registry PAT Rotation Tool")
    print("=" * 60)
    print()

    check_gh_cli()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    target_repos = discover_repositories(base_dir)

    if not target_repos:
        print(f"[!] No workflows referencing '{SECRET_NAME}' were found in {base_dir}.")
        sys.exit(0)

    print(f"Discovered {len(target_repos)} repositories requiring secret '{SECRET_NAME}':")
    for r in target_repos:
        print(f"  - {DEFAULT_OWNER}/{r}")
    print()

    # --- Secure token entry ---------------------------------------------------
    print("Enter the new Personal Access Token (PAT).")
    pat = getpass.getpass(prompt="New REGISTRY_PAT (input hidden): ")
    if not pat.strip():
        print("[ERROR] Token cannot be empty. Aborting.")
        sys.exit(1)

    pat_confirm = getpass.getpass(prompt="Confirm REGISTRY_PAT (input hidden): ")
    if pat.strip() != pat_confirm.strip():
        print("[ERROR] Tokens do not match. Aborting.")
        sys.exit(1)

    pat = pat.strip()

    # --- Token format validation ----------------------------------------------
    if not pat.startswith(_VALID_PAT_PREFIXES):
        print(
            f"[WARNING] Token does not start with a recognised GitHub PAT prefix "
            f"({', '.join(_VALID_PAT_PREFIXES)})."
        )
        proceed = (
            input("  Continue anyway? [y/N]: ").strip().lower()
        )
        if proceed not in ("y", "yes"):
            print("Operation cancelled.")
            sys.exit(0)

    # Show only length — never echo the token itself.
    print(f"\n[+] Token length: {len(pat)} characters.")

    confirm = (
        input(
            f"\nUpdate secret '{SECRET_NAME}' across {len(target_repos)} repositories? [y/N]: "
        )
        .strip()
        .lower()
    )
    if confirm not in ("y", "yes"):
        print("Operation cancelled.")
        sys.exit(0)

    # --- Update secrets -------------------------------------------------------
    # Encode once into a bytearray so we can zero it after the loop.
    pat_bytes = bytearray(pat.encode("utf-8"))

    print("\nUpdating secrets...\n")
    success_count = 0
    fail_count = 0

    try:
        for idx, repo_name in enumerate(target_repos, 1):
            full_repo = f"{DEFAULT_OWNER}/{repo_name}"
            print(f"[{idx}/{len(target_repos)}] {full_repo} ... ", end="", flush=True)

            try:
                subprocess.run(
                    ["gh", "secret", "set", SECRET_NAME, "--repo", full_repo],
                    input=bytes(pat_bytes),  # pass a copy; original stays for next iter
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True,
                )
                print("SUCCESS")
                success_count += 1
            except subprocess.CalledProcessError as err:
                # Truncate stderr to first line to avoid leaking sensitive info.
                err_msg = (
                    err.stderr.decode("utf-8", errors="ignore").split("\n", 1)[0].strip()
                    or "unknown error"
                )
                print(f"FAILED: {err_msg}")
                fail_count += 1
    finally:
        # Best-effort: zero the PAT bytes in memory.
        _zero_bytearray(pat_bytes)
        del pat, pat_confirm  # drop references to the str objects

    print("\n" + "=" * 60)
    print(f"PAT Rotation Summary: {success_count} succeeded, {fail_count} failed.")
    print("=" * 60)


if __name__ == "__main__":
    main()

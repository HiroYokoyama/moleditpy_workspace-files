#!/usr/bin/env python3
"""
roll_zenodo_token.py

Interactive script to rotate/update the Zenodo API token secret across all
MoleditPy repositories in DEV_MAIN that publish to Zenodo.

Companion to roll_registry_pat.py, with the same handling: getpass for hidden
entry, gh CLI for the update, token passed via stdin, memory zeroed after use,
repository names validated against an allowlist before reaching subprocess.

Two differences from the PAT script, both forced by what a Zenodo token is:

  - Zenodo tokens have no recognisable prefix (they are ~60 random
    alphanumerics), so the format check that catches a mistyped GitHub PAT
    cannot work here. Instead the token is *verified against the Zenodo API*
    before anything is written. That is strictly better: a typo is caught by
    the service itself rather than discovered at the next release, after the
    bad value has been copied into every repository.

  - There are two separate tokens. ZENODO_TOKEN publishes to the real archive
    where a DOI is permanent; ZENODO_SANDBOX_TOKEN goes to sandbox.zenodo.org.
    They are not interchangeable, and a sandbox token in the production secret
    fails only at the moment you are trying to publish a release. The script
    verifies against the host matching the secret being rotated, so crossing
    them over is caught here.
"""

import sys
import os
import re
import glob
import json
import argparse
import subprocess
import getpass
import urllib.request
import urllib.error

DEFAULT_OWNER = "HiroYokoyama"

PRODUCTION_SECRET = "ZENODO_TOKEN"
SANDBOX_SECRET = "ZENODO_SANDBOX_TOKEN"

API_HOSTS = {
    PRODUCTION_SECRET: "https://zenodo.org/api",
    SANDBOX_SECRET: "https://sandbox.zenodo.org/api",
}

# Strict pattern: only allow alphanumeric, hyphens, underscores, and dots
# (standard GitHub repository name characters). This prevents directory
# traversal or shell metacharacter injection via crafted folder names.
_SAFE_REPO_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


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


def discover_repositories(secret_name, dev_main_dir=None):
    """Find local repos whose workflows reference *secret_name*."""
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
                    if secret_name in f.read():
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


def verify_token(token, api_base):
    """Ask Zenodo whether the token works. Returns (ok, detail).

    A read-only call: listing depositions touches nothing and publishes
    nothing, so a wrong token costs an error message rather than a bad upload.
    """
    url = f"{api_base}/deposit/depositions?size=1"
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}"}, method="GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        try:
            count = len(json.loads(body))
        except ValueError:
            count = None
        detail = "token accepted"
        if count is not None:
            detail += f" ({count} deposition(s) visible)"
        return True, detail
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False, f"rejected by Zenodo (HTTP {e.code} {e.reason})"
        return False, f"HTTP {e.code} {e.reason}"
    except urllib.error.URLError as e:
        return False, f"could not reach {api_base}: {e.reason}"


def _zero_bytearray(ba: bytearray) -> None:
    """Best-effort zeroing of a bytearray to reduce secret residue in memory."""
    for i in range(len(ba)):
        ba[i] = 0


def parse_args():
    parser = argparse.ArgumentParser(
        description="Rotate the Zenodo API token secret across MoleditPy repos"
    )
    parser.add_argument(
        "--sandbox",
        action="store_true",
        help=f"Rotate {SANDBOX_SECRET} (sandbox.zenodo.org) instead of {PRODUCTION_SECRET}",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip the Zenodo API check (not recommended: a typo then reaches every repo)",
    )
    parser.add_argument(
        "--owner",
        default=DEFAULT_OWNER,
        help=f"GitHub owner (default: {DEFAULT_OWNER})",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    secret_name = SANDBOX_SECRET if args.sandbox else PRODUCTION_SECRET
    api_base = API_HOSTS[secret_name]

    print("=" * 60)
    print("  MoleditPy Zenodo Token Rotation Tool")
    print("=" * 60)
    print(f"  Secret     : {secret_name}")
    print(f"  Zenodo host: {api_base}")
    if not args.sandbox:
        print("  NOTE: this token publishes to the real archive, where a")
        print("        published version's DOI is permanent.")
    print()

    check_gh_cli()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    target_repos = discover_repositories(secret_name, base_dir)

    if not target_repos:
        print(f"[!] No workflows referencing '{secret_name}' were found in {base_dir}.")
        sys.exit(0)

    print(f"Discovered {len(target_repos)} repositories requiring secret '{secret_name}':")
    for r in target_repos:
        print(f"  - {args.owner}/{r}")
    print()

    # --- Secure token entry ---------------------------------------------------
    print(f"Enter the new Zenodo API token for {api_base}.")
    token = getpass.getpass(prompt=f"New {secret_name} (input hidden): ")
    if not token.strip():
        print("[ERROR] Token cannot be empty. Aborting.")
        sys.exit(1)

    token_confirm = getpass.getpass(prompt=f"Confirm {secret_name} (input hidden): ")
    if token.strip() != token_confirm.strip():
        print("[ERROR] Tokens do not match. Aborting.")
        sys.exit(1)

    token = token.strip()

    # Show only length — never echo the token itself.
    print(f"\n[+] Token length: {len(token)} characters.")

    # --- Verify against Zenodo before writing it anywhere ---------------------
    if args.no_verify:
        print("[!] Skipping verification (--no-verify).")
    else:
        print(f"[*] Verifying against {api_base} ... ", end="", flush=True)
        ok, detail = verify_token(token, api_base)
        print("OK" if ok else "FAILED")
        print(f"    {detail}")
        if not ok:
            print(
                "\n[ERROR] Zenodo did not accept this token, so it has NOT been\n"
                "        written to any repository. Check that you generated it\n"
                f"        on {api_base.replace('/api', '')} with the\n"
                "        deposit:write and deposit:actions scopes."
            )
            sys.exit(1)

    confirm = (
        input(
            f"\nUpdate secret '{secret_name}' across {len(target_repos)} repositories? [y/N]: "
        )
        .strip()
        .lower()
    )
    if confirm not in ("y", "yes"):
        print("Operation cancelled.")
        sys.exit(0)

    # --- Update secrets -------------------------------------------------------
    # Encode once into a bytearray so we can zero it after the loop.
    token_bytes = bytearray(token.encode("utf-8"))

    print("\nUpdating secrets...\n")
    success_count = 0
    fail_count = 0

    try:
        for idx, repo_name in enumerate(target_repos, 1):
            full_repo = f"{args.owner}/{repo_name}"
            print(f"[{idx}/{len(target_repos)}] {full_repo} ... ", end="", flush=True)

            try:
                subprocess.run(
                    ["gh", "secret", "set", secret_name, "--repo", full_repo],
                    input=bytes(token_bytes),  # copy; original stays for next iter
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
        # Best-effort: zero the token bytes in memory.
        _zero_bytearray(token_bytes)
        del token, token_confirm  # drop references to the str objects

    print("\n" + "=" * 60)
    print(f"Zenodo Token Rotation Summary: {success_count} succeeded, {fail_count} failed.")
    if fail_count:
        print("Repositories that failed still hold the OLD token.")
    print("=" * 60)

    if fail_count:
        sys.exit(1)


if __name__ == "__main__":
    main()

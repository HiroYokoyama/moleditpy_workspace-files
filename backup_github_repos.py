"""Mirror every moleditpy-related GitHub repository into a local backup directory.

Asks gh for the account's repositories, keeps the ones whose name matches the
moleditpy patterns, and keeps a bare `--mirror` clone of each under the backup
directory. A mirror carries every branch, tag and note, so a lost repository is
restored with a plain `git clone <backup>/repos/<name>.git`. Wiki repositories
are mirrored alongside their repository, and each mirror is packed into a
single-file bundle for copying onto external media. Issue/PR metadata and the
latest release's assets live outside git, so they are saved beside the mirrors
too. Everything a full run produces is therefore on by default; the --no-* flags
trim it down.

Each run starts from an empty destination: an existing backup is deleted and
fetched again. Pass --incremental to update in place, or --resume to skip
completed repositories and retry failed/unfinished ones. Progress is saved after
every repository. Transient connection errors are retried automatically.

  python G:/DEV_MAIN/backup_github_repos.py                   # the full backup
  python G:/DEV_MAIN/backup_github_repos.py --dest E:/backup  # ... elsewhere
  python G:/DEV_MAIN/backup_github_repos.py --all-releases    # every release, not just the latest
  python G:/DEV_MAIN/backup_github_repos.py --incremental      # refresh all in place
  python G:/DEV_MAIN/backup_github_repos.py --resume           # retry failed/unfinished only
  python G:/DEV_MAIN/backup_github_repos.py --retries 5 --timeout 300
  python G:/DEV_MAIN/backup_github_repos.py --no-bundle --no-releases   # mirrors and metadata only
  python G:/DEV_MAIN/backup_github_repos.py --all             # every non-fork repository
  python G:/DEV_MAIN/backup_github_repos.py --dry-run         # list what would run
"""

import argparse
import concurrent.futures
import datetime
import fnmatch
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time

DEFAULT_DEST = os.environ.get(
    "MOLEDITPY_BACKUP_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "backup_github"),
)

# A repository is backed up when its name matches one of these.
PATTERNS = ["moleditpy*", "python_molecular_editor*"]

# git must never stop for a credential prompt: gh's credential helper supplies
# the token, and anything it cannot answer is a failure, not a question.
ENV = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")


RETRIES = 3
COMMAND_TIMEOUT = 180
_TRANSIENT = (
    "connection was reset",
    "connection reset",
    "recv failure",
    "timed out",
    "timeout",
    "tls handshake",
    "ssl connection",
    "could not resolve host",
    "temporary failure",
    "remote end hung up",
    "unexpected disconnect",
    "early eof",
    "ssl_read",
    "curl 56",
    "curl 92",
    "http/2 stream",
    "http 429",
    "http 500",
    "http 502",
    "http 503",
    "http 504",
)


def run(args, *, retry=True):
    network = args[0] == "gh" or (
        args[0] == "git" and any(part in args for part in ("clone", "update", "fetch"))
    )
    attempts = RETRIES + 1 if network and retry else 1
    for attempt in range(attempts):
        try:
            result = subprocess.run(
                args,
                env=ENV,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=COMMAND_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            result = subprocess.CompletedProcess(args, 124, "", "Command timed out")
        message = (result.stderr or "") + (result.stdout or "")
        if result.returncode == 0 or not any(
            word in message.lower() for word in _TRANSIENT
        ):
            return result
        if attempt + 1 < attempts:
            delay = min(2**attempt, 8)
            print(
                f"  [retry {attempt + 1}/{RETRIES}] {args[0]}: {last_line(result)} ({delay}s)",
                flush=True,
            )
            time.sleep(delay)
    return result


def atomic_json(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".backup-", dir=os.path.dirname(os.path.abspath(path))
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def read_manifest(dest):
    try:
        with open(os.path.join(dest, "manifest.json"), encoding="utf-8") as handle:
            data = json.load(handle)
        return (
            data
            if isinstance(data, dict) and isinstance(data.get("repositories", []), list)
            else {}
        )
    except (OSError, ValueError):
        return {}


def last_line(result):
    text = (result.stderr or result.stdout).strip()
    return text.splitlines()[-1] if text else "git failed"


def list_repos(include_forks, patterns, take_all):
    """Every repository to back up, as gh reports them, sorted by name."""
    fields = "name,nameWithOwner,url,isPrivate,isFork,description,updatedAt,diskUsage,hasWikiEnabled"
    result = run(["gh", "repo", "list", "--limit", "500", "--json", fields])
    if result.returncode != 0:
        sys.exit("gh repo list failed:\n" + (result.stderr or result.stdout).strip())
    selected = []
    for repo in json.loads(result.stdout):
        if repo["isFork"] and not include_forks:
            continue
        name = repo["name"].lower()
        if take_all or any(fnmatch.fnmatch(name, p.lower()) for p in patterns):
            selected.append(repo)
    return sorted(selected, key=lambda r: r["name"].lower())


def force_remove(func, path, _exception):
    """rmtree callback: git keeps pack files read-only, which Windows enforces."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


# onerror is deprecated from 3.12 on and onexc does not exist before it.
RMTREE_CALLBACK = {"onexc" if sys.version_info >= (3, 12) else "onerror": force_remove}


def wipe(dest):
    """Empty the destination so the run cannot inherit anything stale.

    Only a directory this script produced is removed: anything else is a
    mistyped --dest, and deleting it would be the worst kind of surprise.
    """
    if not os.path.exists(dest):
        return "fresh"
    ours = os.path.isfile(os.path.join(dest, "manifest.json")) or set(
        os.listdir(dest)
    ) <= {"repos", "bundles", "releases", "metadata", "manifest.json"}
    if not ours:
        sys.exit(
            f"{os.path.abspath(dest)} is not a backup directory (no manifest.json, unfamiliar contents) -- "
            "refusing to delete it."
        )
    shutil.rmtree(dest, **RMTREE_CALLBACK)
    return "deleted the previous backup"


def mirror(url, path):
    """Create or refresh the bare mirror at path. Returns (ok, note)."""
    if os.path.isdir(os.path.join(path, "objects")):
        result = run(["git", "--git-dir", path, "remote", "update", "--prune"])
        action = "updated"
    else:
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        if os.path.lexists(path):
            return (
                False,
                "Incomplete/unrecognised mirror path; move it aside before retrying",
            )
        # Each attempt gets a clean private staging path. A killed/failed clone
        # never makes the final mirror look usable on the next run.
        result = None
        for attempt in range(RETRIES + 1):
            with tempfile.TemporaryDirectory(prefix=".clone-", dir=parent) as staging:
                clone_path = os.path.join(staging, "mirror.git")
                result = run(["git", "clone", "--mirror", url, clone_path], retry=False)
                if result.returncode == 0:
                    os.replace(clone_path, path)
                    break
            message = (result.stderr or "") + (result.stdout or "")
            if attempt >= RETRIES or not any(
                word in message.lower() for word in _TRANSIENT
            ):
                break
            print(
                f"  [retry {attempt + 1}/{RETRIES}] clone: {last_line(result)}",
                flush=True,
            )
            time.sleep(min(2**attempt, 8))
        action = "cloned"
    if result.returncode != 0:
        return False, last_line(result)
    return True, action


def head_sha(path):
    result = run(["git", "--git-dir", path, "rev-parse", "HEAD"])
    return result.stdout.strip() if result.returncode == 0 else ""


def ref_count(path):
    result = run(["git", "--git-dir", path, "for-each-ref", "--format=%(refname)"])
    return len(result.stdout.splitlines()) if result.returncode == 0 else 0


def mirror_refs(path):
    """The mirror's refs as `sha refname` lines, the same shape a bundle lists."""
    result = run(
        ["git", "--git-dir", path, "for-each-ref", "--format=%(objectname) %(refname)"]
    )
    if result.returncode != 0:
        return None
    return sorted(line for line in result.stdout.splitlines() if " refs/" in line)


def bundle_refs(path):
    """The refs an existing bundle carries, or None if it is missing or unreadable."""
    if not os.path.isfile(path):
        return None
    result = run(["git", "bundle", "list-heads", path])
    if result.returncode != 0:
        return None
    return sorted(line for line in result.stdout.splitlines() if " refs/" in line)


def bundle(mirror_path, bundle_path):
    """Publish a complete bundle atomically, preserving the previous one on failure."""
    refs = mirror_refs(mirror_path)
    if refs is None:
        return False, "Could not read mirror refs"
    if not refs:
        return True, "empty repository; no refs to bundle"
    if bundle_refs(bundle_path) == refs:
        return True, "current"
    parent = os.path.dirname(os.path.abspath(bundle_path))
    os.makedirs(parent, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".bundle-", dir=parent) as staging:
        temporary = os.path.join(staging, "repository.bundle")
        result = run(
            ["git", "--git-dir", mirror_path, "bundle", "create", temporary, "--all"]
        )
        if result.returncode != 0:
            return False, last_line(result)
        os.replace(temporary, bundle_path)
    return True, f"{os.path.getsize(bundle_path) / 1024 / 1024:.1f} MB"


def fetch_releases(full_name, directory, every):
    """Download each asset atomically; unfinished releases are retried on resume."""
    listing = run(
        [
            "gh",
            "release",
            "list",
            "--repo",
            full_name,
            "--limit",
            "200",
            "--json",
            "tagName,isLatest",
        ]
    )
    if listing.returncode != 0:
        raise RuntimeError("Release listing failed: " + last_line(listing))
    releases = json.loads(listing.stdout or "[]")
    if not every:
        releases = [r for r in releases if r.get("isLatest")] or releases[:1]
    kept = []
    for release in releases:
        tag = release["tagName"]
        target = release_directory(directory, tag)
        detail = run(
            ["gh", "release", "view", tag, "--repo", full_name, "--json", "assets"]
        )
        if detail.returncode != 0:
            raise RuntimeError("Release details failed: " + last_line(detail))
        assets = json.loads(detail.stdout)["assets"]
        os.makedirs(target, exist_ok=True)
        for asset in assets:
            name = asset["name"]
            if name in (".", "..") or any(c in name for c in "/\\:"):
                raise ValueError("Unsafe release asset filename")
            destination = os.path.join(target, name)
            if asset_current(destination, asset):
                continue
            with tempfile.TemporaryDirectory(prefix=".asset-", dir=target) as staging:
                # --pattern is a glob; escape metacharacters for a literal name.
                pattern = "".join("\\" + c if c in "*?[]\\" else c for c in name)
                result = run(
                    [
                        "gh",
                        "release",
                        "download",
                        tag,
                        "--repo",
                        full_name,
                        "--dir",
                        staging,
                        "--clobber",
                        "--pattern",
                        pattern,
                    ]
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        "Release asset download failed: " + last_line(result)
                    )
                downloaded = os.path.join(staging, name)
                if not asset_current(downloaded, asset):
                    raise RuntimeError("Release asset size/checksum mismatch: " + name)
                os.replace(downloaded, destination)
        atomic_json(
            os.path.join(target, ".backup-complete.json"),
            {"tag": tag, "assets": assets},
        )
        kept.append(tag)
    return kept


def release_directory(directory, tag):
    import re
    import urllib.parse

    reserved = {"CON", "PRN", "AUX", "NUL"} | {
        f"{prefix}{i}" for prefix in ("COM", "LPT") for i in range(1, 10)
    }
    simple = re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", tag)
    if simple and tag.split(".")[0].upper() not in reserved and not tag.endswith("."):
        return os.path.join(directory, tag)
    return os.path.join(directory, "tag~" + urllib.parse.quote(tag, safe=""))


def asset_current(path, asset):
    import hashlib

    if not os.path.isfile(path) or os.path.getsize(path) != asset["size"]:
        return False
    digest = asset.get("digest") or ""
    if digest.startswith("sha256:"):
        hasher = hashlib.sha256()
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(block)
        return digest == "sha256:" + hasher.hexdigest()
    return True


def fetch_metadata(full_name, directory):
    """Save issues, pull requests and release notes as JSON beside the mirrors."""
    os.makedirs(directory, exist_ok=True)
    saved = []
    for name, endpoint in [
        ("issues", "repos/{}/issues?state=all&per_page=100"),
        ("pulls", "repos/{}/pulls?state=all&per_page=100"),
        ("releases", "repos/{}/releases?per_page=100"),
    ]:
        result = run(["gh", "api", "--paginate", "--slurp", endpoint.format(full_name)])
        if result.returncode != 0:
            raise RuntimeError("Metadata download failed: " + last_line(result))
        pages = json.loads(result.stdout)
        atomic_json(
            os.path.join(directory, name + ".json"),
            [row for page in pages for row in page],
        )
        saved.append(name)
    return saved


def back_up(repo, dest, args):
    """Back one repository up. Returns its manifest entry."""
    name = repo["name"]
    entry = {
        "name": name,
        "url": repo["url"],
        "private": repo["isPrivate"],
        "fork": repo["isFork"],
    }
    path = os.path.join(dest, "repos", name + ".git")
    ok, note = mirror(repo["url"], path)
    entry["ok"] = ok
    entry["mirror"] = note if ok else "FAILED: " + note
    if ok:
        entry["head"] = head_sha(path)
        entry["refs"] = ref_count(path)
        if not args.no_bundle:
            bundle_ok, bundle_note = bundle(
                path, os.path.join(dest, "bundles", name + ".bundle")
            )
            entry["bundle"] = bundle_note if bundle_ok else "FAILED: " + bundle_note
            entry["ok"] = bundle_ok

    if not args.no_wiki and repo.get("hasWikiEnabled"):
        wiki_path = os.path.join(dest, "repos", name + ".wiki.git")
        wiki_ok, wiki_note = mirror(repo["url"] + ".wiki.git", wiki_path)
        if wiki_ok:
            entry["wiki"] = wiki_note
            entry["wiki_refs"] = ref_count(wiki_path)
            if not args.no_bundle:
                wiki_bundle_ok, wiki_bundle_note = bundle(
                    wiki_path, os.path.join(dest, "bundles", name + ".wiki.bundle")
                )
                entry["wiki_bundle"] = wiki_bundle_note
                if not wiki_bundle_ok:
                    entry["ok"] = False
                    entry["wiki_bundle"] = "FAILED: " + wiki_bundle_note
        elif os.path.isdir(wiki_path) or not wiki_missing(wiki_note):
            # An enabled-but-never-written wiki has no repository; only a wiki
            # that exists locally and then failed to refresh is a real failure.
            entry["wiki"] = "FAILED: " + wiki_note
            entry["ok"] = False

    if not args.no_releases:
        entry["releases"] = fetch_releases(
            repo["nameWithOwner"],
            os.path.join(dest, "releases", name),
            args.all_releases,
        )
    if not args.no_metadata:
        entry["metadata"] = fetch_metadata(
            repo["nameWithOwner"], os.path.join(dest, "metadata", name)
        )
    entry["requested"] = requested_options(args)
    return entry


def wiki_missing(message):
    return "not found" in message.lower() or "does not exist" in message.lower()


def requested_options(args):
    return {
        key: getattr(args, key)
        for key in (
            "no_bundle",
            "no_wiki",
            "no_releases",
            "no_metadata",
            "all_releases",
        )
    }


def can_resume(entry, repo, dest, args):
    try:
        return _can_resume(entry, repo, dest, args)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        # Damaged local completion data means retry, never skip or abort.
        return False


def _can_resume(entry, repo, dest, args):
    if not entry or entry.get("ok") is not True or entry.get("url") != repo["url"]:
        return False
    if entry.get("requested") != requested_options(args):
        return False
    name = repo["name"]
    mirror_path = os.path.join(dest, "repos", name + ".git")
    if not os.path.isdir(os.path.join(mirror_path, "objects")):
        return False
    if (
        not args.no_bundle
        and entry.get("refs") != 0
        and not os.path.isfile(os.path.join(dest, "bundles", name + ".bundle"))
    ):
        return False
    if entry.get("wiki") and not str(entry["wiki"]).startswith("FAILED"):
        if not os.path.isdir(
            os.path.join(dest, "repos", name + ".wiki.git", "objects")
        ):
            return False
        if (
            not args.no_bundle
            and entry.get("wiki_refs") != 0
            and not os.path.isfile(os.path.join(dest, "bundles", name + ".wiki.bundle"))
        ):
            return False
    if not args.no_metadata and any(
        not os.path.isfile(os.path.join(dest, "metadata", name, key + ".json"))
        for key in ("issues", "pulls", "releases")
    ):
        return False
    if not args.no_releases:
        for tag in entry.get("releases", []):
            target = release_directory(os.path.join(dest, "releases", name), tag)
            marker = read_json_file(os.path.join(target, ".backup-complete.json"))
            if (
                not isinstance(marker, dict)
                or marker.get("tag") != tag
                or not isinstance(marker.get("assets"), list)
            ):
                return False
            if any(
                not asset_current(os.path.join(target, a["name"]), a)
                for a in marker.get("assets", [])
            ):
                return False
    return True


def read_json_file(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dest", default=DEFAULT_DEST, help="backup directory (default: %(default)s)"
    )
    parser.add_argument(
        "--pattern", action="append", default=[], help="extra name pattern (repeatable)"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="back up every repository, not just moleditpy ones",
    )
    parser.add_argument(
        "--include-forks",
        action="store_true",
        help="also back up forks (rdkit, pymatgen: large)",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="update the existing backup in place instead of deleting it first",
    )
    parser.add_argument(
        "--no-bundle",
        action="store_true",
        help="skip the single-file .bundle per mirror",
    )
    parser.add_argument(
        "--all-releases",
        action="store_true",
        help="download every release, not just the latest",
    )
    parser.add_argument(
        "--no-releases", action="store_true", help="skip release assets"
    )
    parser.add_argument(
        "--no-metadata", action="store_true", help="skip the issues/PRs/releases JSON"
    )
    parser.add_argument("--no-wiki", action="store_true", help="skip wiki repositories")
    parser.add_argument(
        "--jobs",
        type=int,
        default=4,
        help="parallel repositories (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="list the selected repositories and stop"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="keep progress and retry failed/unfinished repositories only",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="retries for transient network errors (default: 3)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="timeout per command in seconds (default: 180)",
    )
    args = parser.parse_args()
    if args.jobs < 1 or args.retries < 0 or args.timeout < 1:
        parser.error("jobs/timeout must be positive and retries must be nonnegative")
    global RETRIES, COMMAND_TIMEOUT
    RETRIES, COMMAND_TIMEOUT = args.retries, args.timeout
    args.dest = os.path.abspath(args.dest)

    if run(["gh", "auth", "status"]).returncode != 0:
        sys.exit("gh is not authenticated -- run: gh auth login")

    repos = list_repos(args.include_forks, PATTERNS + args.pattern, args.all)
    if not repos:
        sys.exit("no repositories matched")

    total_mb = sum(r["diskUsage"] for r in repos) / 1024
    print(f"{len(repos)} repositories, {total_mb:.0f} MB on GitHub -> {args.dest}")
    if args.dry_run:
        for repo in repos:
            print(
                "  {:<52} {:>8} KB  {}".format(
                    repo["name"],
                    repo["diskUsage"],
                    "private" if repo["isPrivate"] else "",
                )
            )
        return 0

    previous = read_manifest(args.dest) if args.resume else {}
    if not args.incremental and not args.resume:
        print("  " + wipe(args.dest))
    os.makedirs(args.dest, exist_ok=True)
    previous_entries = {
        e["name"]: e
        for e in previous.get("repositories", [])
        if isinstance(e, dict) and "name" in e
    }
    entries = {}

    def checkpoint(complete=False):
        atomic_json(
            os.path.join(args.dest, "manifest.json"),
            {
                "generated": datetime.datetime.now()
                .astimezone()
                .isoformat(timespec="seconds"),
                "destination": args.dest,
                "complete": complete,
                "repositories": sorted(
                    entries.values(), key=lambda e: e["name"].lower()
                ),
            },
        )

    pending = []
    for repo in repos:
        old = previous_entries.get(repo["name"])
        if args.resume and can_resume(old, repo, args.dest, args):
            entries[repo["name"]] = old
            print("  [skip] {:<52} completed backup".format(repo["name"]), flush=True)
        else:
            entries[repo["name"]] = {
                "name": repo["name"],
                "url": repo["url"],
                "ok": False,
                "mirror": "pending",
            }
            pending.append(repo)
    checkpoint()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs)
    futures = {pool.submit(back_up, repo, args.dest, args): repo for repo in pending}
    interrupted = False
    try:
        for done in concurrent.futures.as_completed(futures):
            repo = futures[done]
            try:
                entry = done.result()
            except Exception as exc:  # noqa: BLE001 - checkpoint each failed repository
                entry = {
                    "name": repo["name"],
                    "url": repo["url"],
                    "ok": False,
                    "mirror": "FAILED: " + str(exc),
                }
            entries[entry["name"]] = entry
            checkpoint()
            detail = entry["mirror"]
            if "bundle" in entry:
                detail += "  bundle: " + entry["bundle"]
            print(
                "  [{}] {:<52} {}".format(
                    "ok " if entry["ok"] else "FAIL", entry["name"], detail
                ),
                flush=True,
            )
    except KeyboardInterrupt:
        interrupted = True
        print("\nInterrupted; checkpoint saved. Re-run with --resume.", flush=True)
        for future in futures:
            future.cancel()
    finally:
        pool.shutdown(wait=not interrupted)
        checkpoint(complete=not interrupted and all(e["ok"] for e in entries.values()))
    if interrupted:
        return 130
    entries = list(entries.values())
    failed = [e["name"] for e in entries if not e["ok"]]
    print(
        f"\n{len(entries) - len(failed)} mirrored, {len(failed)} failed. Restore with: git clone {os.path.abspath(args.dest)}/repos/<name>.git"
    )
    if failed:
        print("failed: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

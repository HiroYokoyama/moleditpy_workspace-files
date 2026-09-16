"""Mirror every moleditpy-related GitHub repository into a local backup directory.

Asks gh for the account's repositories, keeps the ones whose name matches the
moleditpy patterns, and keeps a bare `--mirror` clone of each under the backup
directory. A mirror carries every branch, tag and note, so a lost repository is
restored with a plain `git clone <backup>/repos/<name>.git`. Wiki repositories
are mirrored alongside their repository; release assets and issue/PR metadata
live outside git and are fetched only when asked for.

  python G:/DEV_MAIN/backup_github_repos.py                  # mirror repos + wikis
  python G:/DEV_MAIN/backup_github_repos.py --dest E:/backup  # ... elsewhere
  python G:/DEV_MAIN/backup_github_repos.py --releases --metadata
  python G:/DEV_MAIN/backup_github_repos.py --all            # every non-fork repo
  python G:/DEV_MAIN/backup_github_repos.py --dry-run        # list what would run
"""

import argparse
import concurrent.futures
import datetime
import fnmatch
import json
import os
import subprocess
import sys

DEFAULT_DEST = os.environ.get(
    "MOLEDITPY_BACKUP_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "backup_github"),
)

# A repository is backed up when its name matches one of these.
PATTERNS = ["moleditpy*", "python_molecular_editor*"]

# git must never stop for a credential prompt: gh's credential helper supplies
# the token, and anything it cannot answer is a failure, not a question.
ENV = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")


def run(args):
    return subprocess.run(
        args, env=ENV, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


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


def mirror(url, path):
    """Create or refresh the bare mirror at path. Returns (ok, note)."""
    if os.path.isdir(os.path.join(path, "objects")):
        result = run(["git", "--git-dir", path, "remote", "update", "--prune"])
        action = "updated"
    else:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        result = run(["git", "clone", "--mirror", url, path])
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


def fetch_releases(full_name, directory):
    """Download every release asset not already on disk. Assets are not in git."""
    listing = run(
        ["gh", "release", "list", "--repo", full_name, "--limit", "200", "--json", "tagName"]
    )
    if listing.returncode != 0:
        return 0
    downloaded = 0
    for release in json.loads(listing.stdout or "[]"):
        target = os.path.join(directory, release["tagName"].replace("/", "_"))
        if os.path.isdir(target):
            continue
        os.makedirs(target, exist_ok=True)
        result = run(
            ["gh", "release", "download", release["tagName"], "--repo", full_name,
             "--dir", target, "--pattern", "*"]
        )
        if result.returncode == 0:
            downloaded += 1
        elif not os.listdir(target):
            os.rmdir(target)  # a source-only release has no assets to keep
    return downloaded


def fetch_metadata(full_name, directory):
    """Save issues, pull requests and release notes as JSON beside the mirrors."""
    os.makedirs(directory, exist_ok=True)
    saved = []
    for name, endpoint in [
        ("issues", "repos/{}/issues?state=all&per_page=100"),
        ("pulls", "repos/{}/pulls?state=all&per_page=100"),
        ("releases", "repos/{}/releases?per_page=100"),
    ]:
        result = run(["gh", "api", "--paginate", endpoint.format(full_name)])
        if result.returncode != 0:
            continue
        with open(os.path.join(directory, name + ".json"), "w", encoding="utf-8") as handle:
            handle.write(result.stdout)
        saved.append(name)
    return saved


def back_up(repo, dest, want_releases, want_metadata, want_wiki):
    """Back one repository up. Returns its manifest entry."""
    name = repo["name"]
    entry = {"name": name, "url": repo["url"], "private": repo["isPrivate"], "fork": repo["isFork"]}
    path = os.path.join(dest, "repos", name + ".git")
    ok, note = mirror(repo["url"], path)
    entry["ok"] = ok
    entry["mirror"] = note if ok else "FAILED: " + note
    if ok:
        entry["head"] = head_sha(path)
        entry["refs"] = ref_count(path)

    if want_wiki and repo.get("hasWikiEnabled"):
        wiki_path = os.path.join(dest, "repos", name + ".wiki.git")
        wiki_ok, wiki_note = mirror(repo["url"] + ".wiki.git", wiki_path)
        if wiki_ok:
            entry["wiki"] = wiki_note
        elif os.path.isdir(wiki_path):
            # An enabled-but-never-written wiki has no repository; only a wiki
            # that exists locally and then failed to refresh is a real failure.
            entry["wiki"] = "FAILED: " + wiki_note
            entry["ok"] = False

    if want_releases:
        entry["releases_downloaded"] = fetch_releases(
            repo["nameWithOwner"], os.path.join(dest, "releases", name)
        )
    if want_metadata:
        entry["metadata"] = fetch_metadata(
            repo["nameWithOwner"], os.path.join(dest, "metadata", name)
        )
    return entry


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dest", default=DEFAULT_DEST, help="backup directory (default: %(default)s)")
    parser.add_argument("--pattern", action="append", default=[], help="extra name pattern (repeatable)")
    parser.add_argument("--all", action="store_true", help="back up every repository, not just moleditpy ones")
    parser.add_argument("--include-forks", action="store_true", help="also back up forks (rdkit, pymatgen: large)")
    parser.add_argument("--releases", action="store_true", help="also download release assets")
    parser.add_argument("--metadata", action="store_true", help="also save issues/PRs/releases as JSON")
    parser.add_argument("--no-wiki", action="store_true", help="skip wiki repositories")
    parser.add_argument("--jobs", type=int, default=4, help="parallel repositories (default: %(default)s)")
    parser.add_argument("--dry-run", action="store_true", help="list the selected repositories and stop")
    args = parser.parse_args()

    if run(["gh", "auth", "status"]).returncode != 0:
        sys.exit("gh is not authenticated -- run: gh auth login")

    repos = list_repos(args.include_forks, PATTERNS + args.pattern, args.all)
    if not repos:
        sys.exit("no repositories matched")

    total_mb = sum(r["diskUsage"] for r in repos) / 1024
    print("{} repositories, {:.0f} MB on GitHub -> {}".format(len(repos), total_mb, args.dest))
    if args.dry_run:
        for repo in repos:
            print("  {:<52} {:>8} KB  {}".format(
                repo["name"], repo["diskUsage"], "private" if repo["isPrivate"] else ""))
        return 0

    os.makedirs(args.dest, exist_ok=True)
    entries = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [
            pool.submit(back_up, repo, args.dest, args.releases, args.metadata, not args.no_wiki)
            for repo in repos
        ]
        for done in concurrent.futures.as_completed(futures):
            entry = done.result()
            entries.append(entry)
            print("  [{}] {:<52} {}".format(
                "ok " if entry["ok"] else "FAIL", entry["name"], entry["mirror"]))

    entries.sort(key=lambda e: e["name"].lower())
    manifest = {
        "generated": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "destination": os.path.abspath(args.dest),
        "repositories": entries,
    }
    with open(os.path.join(args.dest, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)

    failed = [e["name"] for e in entries if not e["ok"]]
    print("\n{} mirrored, {} failed. Restore with: git clone {}/repos/<name>.git".format(
        len(entries) - len(failed), len(failed), os.path.abspath(args.dest)))
    if failed:
        print("failed: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

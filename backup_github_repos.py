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

  python G:/DEV_MAIN/backup_github_repos.py                   # the full backup
  python G:/DEV_MAIN/backup_github_repos.py --dest E:/backup  # ... elsewhere
  python G:/DEV_MAIN/backup_github_repos.py --all-releases    # every release, not just the latest
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


def mirror_refs(path):
    """The mirror's refs as `sha refname` lines, the same shape a bundle lists."""
    result = run(["git", "--git-dir", path, "for-each-ref", "--format=%(objectname) %(refname)"])
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
    """Pack the mirror into a single-file bundle. Returns (ok, note)."""
    if bundle_refs(bundle_path) == mirror_refs(mirror_path):
        return True, "current"
    os.makedirs(os.path.dirname(bundle_path), exist_ok=True)
    # Build beside the target so a failed run never truncates the good bundle.
    temporary = bundle_path + ".tmp"
    result = run(["git", "--git-dir", mirror_path, "bundle", "create", temporary, "--all"])
    if result.returncode != 0:
        if os.path.isfile(temporary):
            os.remove(temporary)
        return False, last_line(result)
    os.replace(temporary, bundle_path)
    return True, "{:.1f} MB".format(os.path.getsize(bundle_path) / 1024 / 1024)


def fetch_releases(full_name, directory, every):
    """Download release assets not already on disk. Assets are not in git.

    Only the latest release is kept unless `every` is set: older assets are
    rebuildable from the tagged source the mirror already holds.
    """
    listing = run(
        ["gh", "release", "list", "--repo", full_name, "--limit", "200",
         "--json", "tagName,isLatest"]
    )
    if listing.returncode != 0:
        return 0
    releases = json.loads(listing.stdout or "[]")
    if not every:
        # gh lists newest first, so its first entry stands in when no release
        # carries the "latest" flag.
        releases = [r for r in releases if r.get("isLatest")] or releases[:1]
    kept = []
    for release in releases:
        tag = release["tagName"]
        target = os.path.join(directory, tag.replace("/", "_"))
        if os.path.isdir(target):
            kept.append(tag)
            continue
        os.makedirs(target, exist_ok=True)
        result = run(
            ["gh", "release", "download", tag, "--repo", full_name,
             "--dir", target, "--pattern", "*"]
        )
        if result.returncode == 0:
            kept.append(tag)
        elif not os.listdir(target):
            os.rmdir(target)  # a source-only release has no assets to keep
    if os.path.isdir(directory) and not os.listdir(directory):
        os.rmdir(directory)
    return kept


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


def back_up(repo, dest, args):
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
        if not args.no_bundle:
            bundle_ok, bundle_note = bundle(path, os.path.join(dest, "bundles", name + ".bundle"))
            entry["bundle"] = bundle_note if bundle_ok else "FAILED: " + bundle_note
            entry["ok"] = bundle_ok

    if not args.no_wiki and repo.get("hasWikiEnabled"):
        wiki_path = os.path.join(dest, "repos", name + ".wiki.git")
        wiki_ok, wiki_note = mirror(repo["url"] + ".wiki.git", wiki_path)
        if wiki_ok:
            entry["wiki"] = wiki_note
            if not args.no_bundle:
                bundle(wiki_path, os.path.join(dest, "bundles", name + ".wiki.bundle"))
        elif os.path.isdir(wiki_path):
            # An enabled-but-never-written wiki has no repository; only a wiki
            # that exists locally and then failed to refresh is a real failure.
            entry["wiki"] = "FAILED: " + wiki_note
            entry["ok"] = False

    if not args.no_releases:
        entry["releases"] = fetch_releases(
            repo["nameWithOwner"], os.path.join(dest, "releases", name), args.all_releases
        )
    if not args.no_metadata:
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
    parser.add_argument("--no-bundle", action="store_true", help="skip the single-file .bundle per mirror")
    parser.add_argument("--all-releases", action="store_true", help="download every release, not just the latest")
    parser.add_argument("--no-releases", action="store_true", help="skip release assets")
    parser.add_argument("--no-metadata", action="store_true", help="skip the issues/PRs/releases JSON")
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
            pool.submit(back_up, repo, args.dest, args)
            for repo in repos
        ]
        for done in concurrent.futures.as_completed(futures):
            entry = done.result()
            entries.append(entry)
            detail = entry["mirror"]
            if "bundle" in entry:
                detail += "  bundle: " + entry["bundle"]
            print("  [{}] {:<52} {}".format(
                "ok " if entry["ok"] else "FAIL", entry["name"], detail))

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

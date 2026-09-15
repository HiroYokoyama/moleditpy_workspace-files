"""Survey every MoleditPy repo for open issues, open PRs and un-pushed local work.

Two GitHub searches cover all the remote state at once (rather than one call per
repo), then each sibling checkout is inspected locally for the things a search
cannot see: a dirty worktree, commits that never left the machine, a detached
HEAD, a branch with no upstream.

Run from anywhere:  python G:/DEV_MAIN/check_issues_prs.py

  --owner NAME     GitHub account to search (default HiroYokoyama)
  --local-only     skip the issue/PR search; report checkout hygiene only
  --remote-only    skip the checkout walk; report issues and PRs only
  --tags           also look for unpushed tags (one network call per repo,
                   so the default leaves it out and the run stays local)
  --fail-on-open   exit non-zero when anything at all is outstanding

Authentication comes from `gh`; this script never reads, stores or prints a
token. Exits non-zero on a broken `gh`, and otherwise only with --fail-on-open.
"""

import argparse
import datetime
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OWNER = "HiroYokoyama"

# Mirrors of other people's projects: checked out here to read, never to ship.
NOT_OURS = {"rdkit", "FolioSort"}


def run(args, cwd=None):
    """Return (exit code, stdout). stderr is folded in so failures explain themselves."""
    done = subprocess.run(
        args,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )
    return done.returncode, (done.stdout or "").strip()


def age_days(stamp):
    """Whole days since an ISO-8601 GitHub timestamp."""
    when = datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=datetime.timezone.utc)
    return (datetime.datetime.now(datetime.timezone.utc) - when).days


def search(kind, owner, limit):
    """Open issues or PRs across the owner's repos, as a list of dicts."""
    fields = "repository,number,title,createdAt"
    if kind == "prs":
        fields += ",isDraft"
    code, out = run(
        ["gh", "search", kind, "--owner", owner, "--state", "open",
         "--limit", str(limit), "--json", fields]
    )
    if code != 0:
        raise RuntimeError("gh search %s failed:\n%s" % (kind, out))
    return json.loads(out) if out else []


def checkouts():
    """Every sibling git checkout, as (directory name, absolute path)."""
    for name in sorted(os.listdir(ROOT)):
        path = os.path.join(ROOT, name)
        if name in NOT_OURS or not os.path.isdir(os.path.join(path, ".git")):
            continue
        yield name, path


def local_state(path, want_tags=False):
    """What is in this checkout that GitHub has not seen. Empty list when clean."""
    notes = []

    code, dirty = run(["git", "status", "--porcelain"], cwd=path)
    if code != 0:
        return ["git status failed: %s" % dirty.splitlines()[0]]
    if dirty:
        notes.append("%d uncommitted file(s)" % len(dirty.splitlines()))

    code, branch = run(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], cwd=path)
    if code != 0:
        code, sha = run(["git", "rev-parse", "--short", "HEAD"], cwd=path)
        return notes + ["detached HEAD at %s" % sha]

    code, _ = run(
        ["git", "rev-parse", "--quiet", "--verify", branch + "@{upstream}"], cwd=path
    )
    if code != 0:
        notes.append("branch %s has no upstream" % branch)
        return notes

    code, counts = run(
        ["git", "rev-list", "--left-right", "--count", branch + "...@{upstream}"],
        cwd=path,
    )
    if code == 0 and counts:
        ahead, behind = counts.split()
        if ahead != "0":
            notes.append("%s commit(s) unpushed on %s" % (ahead, branch))
        if behind != "0":
            notes.append("%s commit(s) behind origin" % behind)

    if not want_tags:
        return notes

    code, tags = run(["git", "push", "--tags", "--dry-run", "--porcelain"], cwd=path)
    if code == 0:
        new = [ln for ln in tags.splitlines() if ln.startswith("*\trefs/tags/")]
        if new:
            notes.append("%d unpushed tag(s)" % len(new))

    return notes


def report_remote(owner, limit):
    """Print open issues and PRs. Returns how many were found."""
    issues = [i for i in search("issues", owner, limit) if not i.get("isPullRequest")]
    prs = search("prs", owner, limit)

    for label, rows in (("open PR", prs), ("open issue", issues)):
        if not rows:
            print("No %ss." % label)
            continue
        print("%d %s(s):" % (len(rows), label))
        for row in sorted(rows, key=lambda r: r["createdAt"]):
            draft = " [draft]" if row.get("isDraft") else ""
            print("  %-52s #%-4s %3dd  %s%s" % (
                row["repository"]["name"], row["number"],
                age_days(row["createdAt"]), row["title"][:60], draft))
        print()

    return len(issues) + len(prs)


def report_local(want_tags=False):
    """Print checkout hygiene. Returns how many repos had something outstanding."""
    rows = [(name, local_state(path, want_tags)) for name, path in checkouts()]
    unclean = [(name, notes) for name, notes in rows if notes]

    if not unclean:
        print("All %d checkouts are clean and pushed." % len(rows))
        return 0

    print("%d of %d checkouts need attention:" % (len(unclean), len(rows)))
    for name, notes in unclean:
        print("  %-52s %s" % (name, "; ".join(notes)))
    return len(unclean)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", default=DEFAULT_OWNER)
    parser.add_argument("--limit", type=int, default=200,
                        help="max results per search (default 200)")
    parser.add_argument("--local-only", action="store_true")
    parser.add_argument("--remote-only", action="store_true")
    parser.add_argument("--tags", action="store_true",
                        help="also check for unpushed tags (slower: hits each remote)")
    parser.add_argument("--fail-on-open", action="store_true")
    args = parser.parse_args()

    outstanding = 0

    if not args.local_only:
        try:
            outstanding += report_remote(args.owner, args.limit)
        except (RuntimeError, ValueError) as exc:
            print(exc, file=sys.stderr)
            print("Is `gh auth status` healthy?", file=sys.stderr)
            return 2
        print()

    if not args.remote_only:
        outstanding += report_local(args.tags)

    return 1 if (args.fail_on_open and outstanding) else 0


if __name__ == "__main__":
    sys.exit(main())

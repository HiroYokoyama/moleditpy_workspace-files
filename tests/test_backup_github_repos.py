"""Small, offline backup regressions; no access to user repositories or data."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "backup", Path(__file__).resolve().parents[1] / "backup_github_repos.py"
)
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def result(code=0, out="", err=""):
    return subprocess.CompletedProcess([], code, out, err)


def args(**changes):
    values = {
        "no_bundle": True,
        "no_wiki": True,
        "no_releases": True,
        "no_metadata": True,
        "all_releases": False,
    }
    values.update(changes)
    return types.SimpleNamespace(**values)


class BackupTests(unittest.TestCase):
    def test_transient_reset_retries_but_auth_failure_does_not(self):
        with (
            patch.object(
                backup.subprocess,
                "run",
                side_effect=[
                    result(128, err="Recv failure: Connection was reset"),
                    result(),
                ],
            ) as run,
            patch.object(backup.time, "sleep"),
        ):
            self.assertEqual(backup.run(["git", "fetch"]).returncode, 0)
            self.assertEqual(run.call_count, 2)
        with patch.object(
            backup.subprocess,
            "run",
            return_value=result(128, err="Authentication failed"),
        ) as run:
            self.assertNotEqual(backup.run(["git", "fetch"]).returncode, 0)
            self.assertEqual(run.call_count, 1)

    def test_failed_clone_retries_in_a_new_staging_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = []

            def fake(command, **kw):
                path = Path(command[-1])
                paths.append(path)
                path.mkdir()
                (path / "partial").write_text("unfinished")
                if len(paths) == 1:
                    return result(128, err="Recv failure: Connection was reset")
                (path / "objects").mkdir()
                return result()

            target = Path(temporary) / "repo.git"
            with (
                patch.object(backup, "run", side_effect=fake),
                patch.object(backup.time, "sleep"),
            ):
                self.assertEqual(
                    backup.mirror("https://example.invalid/repo", str(target)),
                    (True, "cloned"),
                )
            self.assertNotEqual(paths[0], paths[1])
            self.assertTrue((target / "objects").is_dir())
            self.assertFalse(paths[0].exists())

    def test_actual_mirror_bundle_and_restore_without_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()

            def git(*arguments):
                return subprocess.run(
                    [
                        "git",
                        "-c",
                        "commit.gpgsign=false",
                        "-c",
                        "user.name=Backup test",
                        "-c",
                        "user.email=backup@example.invalid",
                        *arguments,
                    ],
                    cwd=source,
                    check=True,
                    capture_output=True,
                    text=True,
                )

            git("init")
            (source / "example.txt").write_text("recoverable")
            git("add", "example.txt")
            git("commit", "-m", "fixture")
            mirror = root / "repo.git"
            archive = root / "bundles" / "repo.bundle"
            self.assertTrue(backup.mirror(str(source), str(mirror))[0])
            self.assertTrue(backup.bundle(str(mirror), str(archive))[0])
            self.assertEqual(
                backup.bundle(str(mirror), str(archive)), (True, "current")
            )
            restored = root / "restored"
            git("clone", str(archive), str(restored))
            self.assertEqual((restored / "example.txt").read_text(), "recoverable")

    def test_resume_skips_complete_and_retries_failed_with_checkpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            dest = Path(temporary)
            repos = [
                {"name": n, "url": "https://example.invalid/" + n, "diskUsage": 0}
                for n in ("complete", "failed")
            ]
            (dest / "repos/complete.git/objects").mkdir(parents=True)
            complete = {
                "name": "complete",
                "url": repos[0]["url"],
                "ok": True,
                "mirror": "cloned",
                "requested": backup.requested_options(args()),
            }
            backup.atomic_json(
                str(dest / "manifest.json"),
                {"repositories": [complete, {"name": "failed", "ok": False}]},
            )

            def work(repo, destination, options):
                checkpoint = backup.read_manifest(destination)
                self.assertEqual(
                    next(
                        e for e in checkpoint["repositories"] if e["name"] == "complete"
                    )["ok"],
                    True,
                )
                self.assertEqual(repo["name"], "failed")
                return {
                    "name": repo["name"],
                    "url": repo["url"],
                    "ok": True,
                    "mirror": "cloned",
                }

            command = [
                "backup",
                "--resume",
                "--dest",
                str(dest),
                "--no-bundle",
                "--no-releases",
                "--no-metadata",
                "--no-wiki",
            ]
            with (
                patch.object(sys, "argv", command),
                patch.object(backup, "list_repos", return_value=repos),
                patch.object(backup, "run", return_value=result()),
                patch.object(backup, "back_up", side_effect=work) as run,
                patch.object(
                    backup, "wipe", side_effect=AssertionError("must not wipe")
                ),
            ):
                self.assertEqual(backup.main(), 0)
                self.assertEqual(run.call_count, 1)
            self.assertTrue(backup.read_manifest(str(dest))["complete"])

    def test_exception_is_checkpointed_and_other_repository_continues(self):
        with tempfile.TemporaryDirectory() as temporary:
            repos = [{"name": n, "url": n, "diskUsage": 0} for n in ("bad", "good")]

            def work(repo, *unused):
                if repo["name"] == "bad":
                    raise RuntimeError("metadata timed out")
                return {"name": "good", "ok": True, "mirror": "cloned"}

            with (
                patch.object(sys, "argv", ["backup", "--resume", "--dest", temporary]),
                patch.object(backup, "list_repos", return_value=repos),
                patch.object(backup, "run", return_value=result()),
                patch.object(backup, "back_up", side_effect=work),
            ):
                self.assertEqual(backup.main(), 1)
            saved = backup.read_manifest(temporary)
            self.assertFalse(saved["complete"])
            self.assertEqual(len(saved["repositories"]), 2)

    def test_paginated_metadata_is_valid_flat_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(
                backup, "run", return_value=result(out='[[{"id": 1}], [{"id": 2}]]')
            ):
                self.assertEqual(len(backup.fetch_metadata("owner/repo", temporary)), 3)
            self.assertEqual(
                json.loads((Path(temporary) / "issues.json").read_text()),
                [{"id": 1}, {"id": 2}],
            )

    def test_failed_partial_asset_is_not_marked_complete(self):
        with tempfile.TemporaryDirectory() as temporary:
            responses = [
                result(out='[{"tagName":"v1","isLatest":true}]'),
                result(out='{"assets":[{"name":"data.zip","size":100}]}'),
                result(1, err="Connection was reset"),
            ]
            with (
                patch.object(backup, "run", side_effect=responses),
                self.assertRaises(RuntimeError),
            ):
                backup.fetch_releases("owner/repo", temporary, False)
            self.assertFalse((Path(temporary) / "v1/.backup-complete.json").exists())

    def test_missing_asset_invalidates_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            dest = Path(temporary)
            (dest / "repos/example.git/objects").mkdir(parents=True)
            options = args(no_releases=False)
            entry = {
                "ok": True,
                "url": "repo",
                "requested": backup.requested_options(options),
                "releases": ["v1"],
            }
            backup.atomic_json(
                str(dest / "releases/example/v1/.backup-complete.json"),
                {"tag": "v1", "assets": [{"name": "gone.zip", "size": 5}]},
            )
            self.assertFalse(
                backup.can_resume(
                    entry, {"name": "example", "url": "repo"}, str(dest), options
                )
            )


if __name__ == "__main__":
    unittest.main()

"""R46 ship.sh dist-mirror sync regression tests.

Regression filed 2026-08-08:

After every ``ship.sh`` run, ``dist/lms_saas-publish/`` was left with
uncommitted modifications because:

  - The publish step regenerates ``dist/lms_saas-publish/`` from
    ``apps/lms_saas/`` source.
  - The original ``ship.sh`` committed the source-repo working tree
    BEFORE publish (step 2.5), so the regenerated mirror was never
    captured.
  - ``.gitignore`` has a ``dist/`` rule that blocks ``git add`` for
    newly-modified tracked files, so even manually re-staging them
    requires ``git add -f``.
  - Net effect: every ship leaves 3-5 `` M dist/lms_saas-publish/...``
    rows in ``git status`` that the developer has to clean up
    manually.

Fix (R46):

  - Step 1.9 pre-syncs any pre-existing mirror drift before publish
    (no-op when already in sync).
  - Step 4.5 re-syncs the regenerated mirror after publish + push.
  - Step 4.6 commits the source repo (including the freshly staged
    mirror) and pushes it.
  - Result: ``git status`` is clean after every ship.

These tests are source-level assertions on ``scripts/ship.sh``. They
exist so a future refactor can't reintroduce the lingering-files bug
without test failure.
"""

import os
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
SHIP_SCRIPT = REPO_ROOT / "scripts" / "ship.sh"


def _read_ship() -> str:
    return SHIP_SCRIPT.read_text()


class TestR46ShipDistSync(unittest.TestCase):
    """R46 ship.sh dist-mirror sync regression coverage."""

    # --------------------------------------------------------------
    # R46-C1: ship.sh must define a Step 1.9 that pre-syncs the
    # dist mirror before publish. This ensures any pre-existing
    # mirror drift (from a previous incomplete ship) doesn't
    # contaminate the next publish.
    # --------------------------------------------------------------
    def test_step_19_pre_syncs_dist_mirror_before_publish(self):
        """Without this pre-sync, the working tree can be in a state
        where Step 2 (publish) regenerates files that were already
        stale, and Step 4.5 (post-sync) might miss them."""
        src = _read_ship()
        # Find step 1.9 block (must reference the dist mirror path).
        m = re.search(
            r"# ── Step 1\.9.*?(?=# ── Step [0-9])", src, flags=re.DOTALL
        )
        self.assertIsNotNone(m, msg="Step 1.9 block not found in ship.sh")
        block = m.group(0)
        self.assertIn(
            "dist/lms_saas-publish",
            block,
            msg="Step 1.9 must reference the publish mirror path",
        )
        # Step 1.9 must come BEFORE Step 2 (publish).
        step19_idx = src.find("Step 1.9")
        step2_idx = src.find("Step 2:")  # "Step 2: Publish"
        self.assertNotEqual(step19_idx, -1)
        self.assertNotEqual(step2_idx, -1)
        self.assertLess(step19_idx, step2_idx, msg="Step 1.9 must run before Step 2 (publish)")

    # --------------------------------------------------------------
    # R46-C1: ship.sh must define a Step 4.5 that re-syncs the
    # regenerated mirror AFTER publish. Without this step the
    # mirror drift would still leak into git status.
    # --------------------------------------------------------------
    def test_step_45_resyncs_dist_mirror_after_publish(self):
        """After publish regenerates the mirror, we MUST stage the
        regenerated files before the source-repo commit — otherwise
        the regenerated files leak into git status."""
        src = _read_ship()
        # Find step 4.5 block.
        m = re.search(
            r"# ── Step 4\.5.*?(?=# ── Step [0-9])", src, flags=re.DOTALL
        )
        self.assertIsNotNone(m, msg="Step 4.5 block not found in ship.sh")
        block = m.group(0)
        self.assertIn(
            "dist/lms_saas-publish",
            block,
            msg="Step 4.5 must reference the publish mirror path",
        )
        self.assertIn(
            "git add -f",
            block,
            msg="Step 4.5 must force-add (override .gitignore's dist/ rule)",
        )
        # Step 4.5 must come AFTER Step 2 (publish) — that's the whole
        # point of the post-sync.
        step45_idx = src.find("Step 4.5")
        step2_idx = src.find("Step 2:")  # "Step 2: Publish"
        self.assertNotEqual(step45_idx, -1)
        self.assertNotEqual(step2_idx, -1)
        self.assertGreater(step45_idx, step2_idx, msg="Step 4.5 must run after Step 2 (publish)")

    # --------------------------------------------------------------
    # R46-C1: ship.sh must define a Step 4.6 (or equivalent) that
    # commits the source-repo AFTER step 4.5 has staged the mirror.
    # --------------------------------------------------------------
    def test_step_46_commits_source_repo_after_mirror_sync(self):
        """The source-repo commit must run AFTER step 4.5 — otherwise
        the regenerated mirror would still be left unstaged."""
        src = _read_ship()
        m = re.search(
            r"# ── Step 4\.6.*?(?=# ── Step [0-9])", src, flags=re.DOTALL
        )
        self.assertIsNotNone(m, msg="Step 4.6 block not found in ship.sh")
        block = m.group(0)
        self.assertIn(
            "git commit",
            block,
            msg="Step 4.6 must commit the source-repo working tree",
        )
        # Step 4.6 must come AFTER Step 4.5.
        step46_idx = src.find("Step 4.6")
        step45_idx = src.find("Step 4.5")
        self.assertNotEqual(step46_idx, -1)
        self.assertNotEqual(step45_idx, -1)
        self.assertGreater(step46_idx, step45_idx, msg="Step 4.6 must run after Step 4.5")

    # --------------------------------------------------------------
    # R46-C1: the original Step 2.5 (commit source-repo BEFORE
    # publish) must NOT exist anymore — that was the bug.
    # --------------------------------------------------------------
    def test_old_pre_publish_source_repo_commit_is_gone(self):
        """The original bug was that Step 2.5 committed the source
        repo before publish, so the regenerated mirror was never
        captured. That step must be removed in R46."""
        src = _read_ship()
        # The old step 2.5 had this exact header (or close to it).
        self.assertNotIn(
            "Step 2.5:",
            src,
            msg="The old pre-publish Step 2.5 must be removed",
        )

    # --------------------------------------------------------------
    # R46-C1: the dist-mirror sync must use `git add -f`, not plain
    # `git add` — otherwise .gitignore's `dist/` rule blocks re-staging
    # of tracked-but-ignored files.
    # --------------------------------------------------------------
    def test_dist_mirror_sync_uses_force_add(self):
        """git add on a tracked-but-ignored file is a no-op unless
        you use -f. R46 must use -f in BOTH step 1.9 and 4.5."""
        src = _read_ship()
        # Step 1.9 must use git add -f
        m19 = re.search(
            r"# ── Step 1\.9.*?(?=# ── Step [0-9])", src, flags=re.DOTALL
        )
        self.assertIsNotNone(m19)
        self.assertIn(
            "git add -f",
            m19.group(0),
            msg="Step 1.9 must use git add -f to override the .gitignore dist/ rule",
        )
        # Step 4.5 must use git add -f
        m45 = re.search(
            r"# ── Step 4\.5.*?(?=# ── Step [0-9])", src, flags=re.DOTALL
        )
        self.assertIsNotNone(m45)
        self.assertIn(
            "git add -f",
            m45.group(0),
            msg="Step 4.5 must use git add -f to override the .gitignore dist/ rule",
        )

    # --------------------------------------------------------------
    # R46-C1: the dist-mirror sync must explicitly enumerate files
    # (not `git add -A` on the whole working tree). Otherwise it
    # would pick up operator scratch files in dist/ that the
    # .gitignore rule is intentionally keeping out of the repo.
    # --------------------------------------------------------------
    def test_dist_mirror_sync_lists_files_explicitly(self):
        """Using `git diff --name-only` + explicit `git add -f` keeps
        the sync scoped to tracked-mirror files. We do NOT want
        `git add -A` here because the operator might have scratch
        files in dist/ that should stay ignored."""
        src = _read_ship()
        # Step 1.9 must use git diff --name-only + xargs (file-list)
        m19 = re.search(
            r"# ── Step 1\.9.*?(?=# ── Step [0-9])", src, flags=re.DOTALL
        )
        self.assertIsNotNone(m19)
        self.assertIn(
            "git diff --name-only",
            m19.group(0),
            msg="Step 1.9 must enumerate files via git diff --name-only",
        )
        # Step 4.5 same
        m45 = re.search(
            r"# ── Step 4\.5.*?(?=# ── Step [0-9])", src, flags=re.DOTALL
        )
        self.assertIsNotNone(m45)
        self.assertIn(
            "git diff --name-only",
            m45.group(0),
            msg="Step 4.5 must enumerate files via git diff --name-only",
        )


if __name__ == "__main__":
    unittest.main()

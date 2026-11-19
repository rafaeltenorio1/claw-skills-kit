# This release is broken on purpose

It exists to demonstrate the reconciler's rollback on a real gateway. `meeting-notes/SKILL.md` has a typo in its
frontmatter (`desciption:` instead of `description:`), so OpenClaw cannot load the skill. Its pins match its files,
as they would for a release that passed review but breaks on a host.

What should happen when it is applied: the smoke check `lk host verify-skills` finds `meeting-notes` missing, the
reconciler restores every file it touched and verifies them by reading them back, and reports `rolled_back`
(exit 6). The host keeps the previous release.

It lives in `library/demo-releases/`, outside the library the agent sees, and is added to it only when the
image is built with `CSK_DEMO_ROLLBACK=1 docker/up.sh`; a plain `docker/up.sh` leaves it out again.

The agent does not read this file; `tests/test_library.py` checks that the defect is still there.

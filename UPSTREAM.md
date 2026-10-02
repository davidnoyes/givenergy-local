# Upstream sync

This fork tracks [cdpuk/givenergy-local](https://github.com/cdpuk/givenergy-local) but
diverges from it on purpose, so upstream changes are reviewed and ported by hand rather than
merged. This file records the policy and every upstream change reviewed so far.

A daily job (the `upstream-sync` workflow in the owner's server repository) compares
upstream `master` with the marker below. When upstream has moved, it ports the new commits
into a PR on this fork and posts it to Discord. Merging that PR moves the marker; the job
waits while a sync PR is open.

Last reviewed upstream commit: `a2fe618268dfed86e43b1ce2b3f1be14fffe1a95` (#159, 2026-09-10)

## Porting policy

- **Keep the fork's design.** The fork has its own recovery coordinator
  (`coordinator.py`: trusted snapshots, failure categories, reconnect backoff) and keeps the
  vendored `givenergy_modbus` library. Upstream fixes are adapted to those, not the other way
  round.
- **Port** bug fixes and robustness changes that apply to the fork, adapted to its code, with
  tests.
- **Consider** new features case by case; port them if they fit and are wanted.
- **Skip** changes that only make sense with upstream's external `givenergy-modbus` library,
  upstream's dependency and tooling setup (uv, pyproject), and version bumps: the fork's
  release-please sets versions.
- The owner's own upstream PRs come from this fork's branches. If upstream merges one, it is
  already here: record it as present.

## Log

| Upstream | Decision | Reason |
|---|---|---|
| v2.4.0 and earlier | Merged | Synced as fork v2.5.0. |
| #141 sync_clock timezone | Already present | The fork already used `dt_util.now()`. |
| #144 external givenergy-modbus library | Not taken | The fork keeps the vendored library. |
| #148 defensive checks for multi-register sensors | Ported (v2.6.1) | Adapted to the fork's consumption formulas. |
| #149, #153 battery charge register fallbacks | Not needed | The fork still reads IR 36/37, the registers they fall back to. |
| #151 connection timeout handling | Ported (v2.6.1) | Into the recovery coordinator: bounded close with client replacement, bounded connect, reconnect backoff, bounded commands, reload via `async_reload`. |
| #152 request collisions | Ported (v2.6.1) | The batch dedupe. The slot helpers are external-library only. |
| #154 version bump | Not taken | Release-please sets the fork's versions. |
| #159 uv and Python 3.14 tooling | Not taken | Upstream's tooling; the fork keeps its requirements files. |

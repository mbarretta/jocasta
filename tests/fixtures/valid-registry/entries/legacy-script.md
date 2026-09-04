---
name: legacy-script
owner: bob
source: https://github.com/example-org/legacy-script
kind: script
registered: 2025-11-20
status: deprecated
deprecated:
  route: owner
  date: 2026-08-15
  note: Superseded by example-cli, which handles nested directories.
---
Prints the top-level directories a branch touched, one per line. Shell only,
no dependencies.

Deprecated by its owner in favor of example-cli. It still runs, but it does
not understand nested directories and will not be fixed.

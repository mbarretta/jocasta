---
name: example-cli
owner: alice
source: https://github.com/example-org/example-cli
kind: cli
install: brew install example-org/tap/example-cli
registered: 2026-09-01
status: active
---
Lists the files in a directory tree that changed since a given git ref and
groups them by the top-level directory they live in.

Reach for it when you want to know which parts of a large repo a branch
touched without reading the whole diff. It is not a diff viewer and it does
not show file contents.

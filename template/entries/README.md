Each file in this directory is one entry in the archive: `<name>.md`, a short
YAML frontmatter block that says what the tool is called, who owns it, where its
source lives, what kind of thing it is and whether it is still active, followed
by a prose description written for the person who will search for it. You do
not write these files by hand; the jocasta skill interviews you and writes a
valid one, and the `validate` workflow refuses anything malformed, unreachable,
unowned or duplicated. The exact format, with the reason every field earns its
place, is documented in the machinery repo at
<https://github.com/mbarretta/jocasta/blob/v1/skills/jocasta/references/schema.md>.

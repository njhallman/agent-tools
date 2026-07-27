---
name: overleaf-tracked-changes
description: Read and edit this project's Overleaf documents as real tracked changes (accept/reject suggestions in Overleaf's review panel) from a terminal session, with no browser. Use this whenever the user asks for edits to be made "in Overleaf", "as tracked changes", "as suggestions", or "so I can accept or reject them", or asks what is currently in the Overleaf copy versus git, or mentions that they are working in Overleaf and wants changes to land there rather than in the repo. Also use it before editing LaTeX in git if the user may be editing in Overleaf concurrently, since the two copies can diverge.
---

# Editing Overleaf with tracked changes

Overleaf's track-changes state lives only inside Overleaf — pushing LaTeX
through the repo's git sync lands as a plain update, never as a reviewable
suggestion. This skill talks to Overleaf's realtime editing protocol directly,
so edits show up in the review panel with accept/reject buttons, attributed to
whichever account the session cookie belongs to.

Everything runs through `scripts/overleaf_client.py`, in this skill's own
directory. `requests` is its only dependency. The protocol details it encodes
were established by experiment; `references/protocol-notes.md` explains each one
and why it matters. Read that file before changing the client — several of the
behaviors are silent failures rather than errors.

## Running the client

Where this skill's directory sits depends on how it was installed — a plugin
lands in a shared cache, a vendored copy under the repo's `.claude/skills/`.
Rather than hard-code either, resolve the path once per session and reuse it:

```bash
CLIENT=$(find ~/.claude/plugins/cache .claude/skills -name overleaf_client.py 2>/dev/null | head -1)
python3 "$CLIENT" list
```

Every example below uses `$CLIENT` and assumes that resolution has been done. If
the absolute path is already known, use it directly instead. If `find` returns
nothing the skill is installed somewhere else — locate `overleaf_client.py` and
call it by full path; do not guess a layout.

## Setup: the session cookie

Authentication is a browser session cookie, exported as an environment variable:

```bash
export OVERLEAF_SESSION='s%3A...'      # the overleaf_session2 value
```

Ask the user to fetch it — in Safari: Settings → Advanced → "Show features for
web developers", then ⌥⌘I on an Overleaf tab → **Storage** → Cookies →
`www.overleaf.com` → copy the **Value** of `overleaf_session2`. Chrome/Firefox:
dev tools → Application/Storage → Cookies. The cookie is HttpOnly, so
`document.cookie` in the console will not show it.

Why not something less awkward: Overleaf has no public editing API, its login
form requires a reCAPTCHA token that only a real browser can mint, Google SSO
accounts have no password to use, and headless browsers cannot complete a TLS
handshake through some sandboxed environments' intercepting proxy. A cookie
from an already-authenticated browser sidesteps all of it.

Treat the value like a password: it is a full session. Keep it in the
environment, never in a file in the repo. It expires, and logging that browser
session out invalidates it — if calls suddenly fail, ask for a fresh one.

If the user wants suggestions attributed to a name other than their own, a
second Overleaf account added as an editor works well and reads more clearly in
the review panel.

## Setup: which project

The client resolves the target project from `--project`, else
`$OVERLEAF_PROJECT_ID`, else the nearest `.claude/overleaf-project-id` file
walking up from the working directory. It refuses to run when none is set
rather than falling back to a default.

```bash
echo <24-hex-id-from-the-project-URL> > .claude/overleaf-project-id   # per repository
```

Two things about that location. It is **per repository, not per skill**: when
this skill is installed as a plugin its directory is a cache shared by every
project on the machine, so an id stored next to the script would be inherited
by whichever repo ran next. And there is deliberately **no default**, because
the failure a default causes is invisible — a stale id keeps editing the
previous project's paper, and since anchors either match or abort the run,
nothing in the output says the edits landed in the wrong manuscript.

Nothing beside the script is consulted, so there is no way to leave an id in
the plugin cache where the next project would inherit it.

## Workflow

**1. Verify before you edit.** Overleaf and git drift apart whenever the user
works in either place, and edits are positional — acting on a stale copy puts
text in the wrong location.

```bash
python3 "$CLIENT" verify main.tex LaTeX/main.tex
```

Exit code 0 means identical. If it differs, `read` the Overleaf copy and diff it
before doing anything else — the Overleaf side is authoritative for what the
user is looking at.

**2. Check what is already in flight.** `changes main.tex` lists existing
suggestions with line numbers and authors. If the user has unresolved tracked
changes of their own, say so before adding more: suggestions interleave in the
review panel, and it is easy to hand back a document that is confusing to
review.

**3. Describe edits by anchor text, not position.** Write a JSON file of exact
replacements:

```json
[
  {"find": "text that appears exactly once", "replace": "the new text"},
  {"find": "sentence to delete entirely.", "replace": ""},
  {"insert_before": "anchor text", "text": "inserted text "}
]
```

The client refuses an anchor that matches zero times or more than once rather
than guessing, because a wrong offset corrupts prose somewhere unrelated and
the damage is not obvious in a diff of a 100k-character file. When an anchor is
ambiguous, extend it with surrounding words until it is unique.

**Fast path for iterative work.** When the user is reviewing in Overleaf and
wants quick turnaround, use `batch`: it takes one JSON object mapping doc paths
to edit lists and applies everything over a single connection, which is a few
seconds rather than one connection per document.

```bash
python3 "$CLIENT" batch --edits /tmp/batch.json     # applies; --dry-run to preview
```

```json
{
  "main.tex": [{"find": "...", "replace": "..."}],
  "Response Memos/JAE_editor_round_2.tex": [{"find": "...", "replace": "..."}]
}
```

Batch applies by default because anchors are validated before anything is
sent -- a missing or ambiguous anchor aborts the run without writing. Reserve
the separate dry-run/read-back/compile cycle below for edits that change LaTeX
structure, references, or numbers; for prose it just costs the user time.

**4. Dry run, then apply.**

```bash
python3 "$CLIENT" edit main.tex --edits /tmp/edits.json          # preview: line numbers + ops
python3 "$CLIENT" edit main.tex --edits /tmp/edits.json --apply  # send as tracked changes
```

Apply re-reads the document afterward and reports the new version and how many
tracked changes were added, which is the confirmation that the edit registered
as a *suggestion* and not a silent overwrite.

**5. Tell the user where to look.** Give line numbers and a one-line summary per
edit so they can review efficiently. They accept or reject in Overleaf; nothing
else is needed from this side.

## Commands

| Command | What it does |
|---|---|
| `list` | every doc in the project with its id |
| `read PATH [-o FILE]` | current Overleaf text of a doc |
| `verify PATH LOCAL` | compare against a local file (exit 0 = identical) |
| `changes PATH` | existing tracked changes, with line numbers and authors |
| `edit PATH --edits F.json [--apply]` | apply anchor-based edits as suggestions |
| `accept PATH [--apply] [--mine-only]` | resolve tracked changes in a doc |
| `bundle` | print a self-contained installer for this skill |

Paths are matched by suffix, so `main.tex` resolves `/LaTeX/main.tex`. There is
no default project id: the client takes `--project`, else `$OVERLEAF_PROJECT_ID`,
else the nearest `.claude/overleaf-project-id` walking up from the working
directory, and exits 1 with instructions when none is set. Add `--verbose` to
see raw protocol frames when debugging, and `--untracked` only if the user
explicitly wants a normal edit rather than a suggestion.

## Accepting changes

`accept` resolves suggestions. Two things make it less alarming than it
sounds, and one makes it worth pausing over:

- **It does not change the document text.** An accepted insertion is already
  present and an accepted deletion is already gone, so accepting only clears
  the markers. Verified: text hashes are byte-identical before and after.
- **It is one-way.** The ranges hold the deleted text, which is what a reject
  would restore, so once cleared there is no going back. Before a bulk accept,
  save `GET /project/<pid>/ranges` somewhere — that JSON is the record of what
  was resolved, including the old wording of every replacement.
- **Confirm scope before running it.** "Accept the changes" can mean one file
  or the whole project, and the user's own in-progress suggestions may be
  mixed in with yours. `--mine-only` restricts to this account's changes; the
  default dry run lists exactly what would be resolved.

`GET /project/<pid>/ranges` returns every doc's changes at once, which is the
fast way to survey a project rather than joining each document.

## Installing this skill in another repository

Preferred: install it from the `njhallman/agent-tools` marketplace, so fixes
propagate instead of being snapshotted. Add to that repo's committed
`.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "agent-tools": { "source": { "source": "github", "repo": "njhallman/agent-tools" } }
  },
  "enabledPlugins": { "overleaf-tracked-changes@agent-tools": true }
}
```

then write that project's `.claude/overleaf-project-id`. Because the settings
live in the repository, a fresh cloud session picks the skill up on its own.

Fallback, when the marketplace is not reachable (a private repo in a
scope-limited session, say): `bundle` prints one self-contained Python
installer carrying this file, the protocol notes, and the client as a
compressed payload.

```bash
python3 "$CLIENT" bundle > /tmp/install_overleaf_skill.py   # then run from the repo root
```

It writes `.claude/skills/overleaf-tracked-changes/` and prints what to set
next. Commit the result — in cloud sessions the repository is the only thing
that survives, so an install into `~/.claude/skills/` would be gone next
session. The payload is a snapshot, not a link, so re-export after changing the
client or these docs.

Whichever route, don't end up with both: a vendored copy and the plugin share a
skill name, and fixing a bug in one while invoking the other is a bad afternoon.

## Things worth knowing

**Tracked changes sync to git as if accepted.** The document text that git
receives contains tracked insertions and omits tracked deletions. So a git
working copy can look like the user's in-progress suggestions are already
final — do not treat the repo as evidence that a suggestion was accepted.

**Small, separately reviewable edits beat one large rewrite.** Each op becomes
its own accept/reject unit; a single suggestion spanning three paragraphs is
all-or-nothing for the reviewer.

**Prefer editing where the user is not.** If they are actively working in a
file, either coordinate first or edit a different one. Overleaf merges
concurrent edits, but interleaved suggestions from two authors in the same
paragraph are unpleasant to review.

**A comment line is a good place to test.** If you need to prove the mechanism
end to end, insert into an existing `%` comment: even accepted, it cannot
change the compiled PDF.

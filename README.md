# agent-tools

A Claude Code plugin marketplace for tooling that is useful across projects
rather than tied to one of them.

## Using it from a project

Add to that project's committed `.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "agent-tools": { "source": { "source": "github", "repo": "njhallman/agent-tools" } }
  },
  "enabledPlugins": { "overleaf-tracked-changes@agent-tools": true }
}
```

Because the settings live in the repository, a fresh session picks the plugin
up on its own — including cloud sessions, where the container is discarded
afterward and only the repository survives.

To try something without committing to it:

```bash
claude plugin marketplace add njhallman/agent-tools
claude plugin install overleaf-tracked-changes@agent-tools
```

## Plugins

Entries fall into two kinds. `overleaf-tracked-changes` is maintained here, in
`plugins/`. Everything under [Writing](#writing) is third-party work referenced
from its upstream repository, so this marketplace is a curated index rather than
a fork — see [Referenced plugins](#referenced-plugins).

### overleaf-tracked-changes

Reads and edits Overleaf documents as real accept/reject suggestions from a
terminal session, with no browser. Its one-shot review command returns a full
tracked replacement, surrounding source, and the attached collaborator
discussion over one connection. Overleaf's track-changes state exists only
inside Overleaf, so LaTeX pushed through its git sync always arrives as a plain
update; this drives the realtime protocol directly instead.

Needs an `overleaf_session2` cookie in `$OVERLEAF_SESSION` and a per-repository
`.claude/overleaf-project-id`. The skill's own documentation covers both, along
with the protocol details — most of which are silent failures rather than
errors, and are written down so they don't have to be rediscovered.

### Writing

Two jobs that are easy to conflate: making prose stop sounding machine-generated,
and making it read like a paper. The first two below do the former on any text;
the last three know what a manuscript is. Star counts are from August 2026 and
are only a rough proxy for how well-exercised each one is.

| Plugin | Invoke as | Upstream | Stars | Always-on |
| :-- | :-- | :-- | --: | --: |
| `humanizer` | `humanizer` | [blader/humanizer](https://github.com/blader/humanizer) | ~35.8k | ~170 tok |
| `stop-slop` | `stop-slop` | [hardikpandya/stop-slop](https://github.com/hardikpandya/stop-slop) | ~15.7k | ~60 tok |
| `academic-humanizer` | `academic-humanizer` | [AIScientists-Dev/academic-humanizer](https://github.com/AIScientists-Dev/academic-humanizer) | ~958 | ~182 tok |
| `paper-writing-skill` | `paper-writing` | [SNL-UCSB/paper-writing-skill](https://github.com/SNL-UCSB/paper-writing-skill) | ~163 | ~275 tok |
| `academic-writing-agents` | `academic` | [andrehuang/academic-writing-agents](https://github.com/andrehuang/academic-writing-agents) | ~161 | ~702 tok |

All five are MIT licensed. Two answer to a name that differs from the plugin's,
hence the second column.

- **humanizer** — rewrites against the 33 patterns in Wikipedia's "Signs of AI
  writing", in two passes, and can calibrate to a voice profile built from your
  own earlier writing.
- **stop-slop** — narrower and much cheaper. Bans throat-clearing openers,
  business jargon, and binary-contrast sentence shapes, then scores the result on
  directness, rhythm, trust, authenticity, and density.
- **academic-humanizer** — the same de-AI pass with scholarly convention held
  intact: citations, data, and numbers are left alone, and claims are pinned to
  the strength the evidence supports (`prove` becomes `show empirically`). Has an
  NSF/NIH proposal mode.
- **paper-writing-skill** — a five-stage pipeline (brainstorm, architect, draft,
  integrate, compress) with per-section rhetorical moves, a style audit on every
  edit, and an independent red-team pass. Calibrated for systems and ML venues.
- **academic-writing-agents** — 12 specialist reviewers run in parallel over a
  draft covering prose, structure, math notation, figures, and bibliography. It
  activates on `.tex` files and will rewrite, not just report. By far the most
  expensive of the set; enable it for manuscript work rather than by default.

Enabling all five costs roughly 1.4k tokens of always-on context per session, so
it is worth turning on only the ones a given repository actually needs:

```json
{
  "enabledPlugins": {
    "humanizer@agent-tools": true,
    "academic-humanizer@agent-tools": true
  }
}
```

The general and academic de-AI passes overlap, and running both over one draft
tends to flatten it. Prefer `academic-humanizer` on manuscripts and `humanizer`
elsewhere.

## Conventions

- One directory per plugin maintained here under `plugins/`, each with its own
  `.claude-plugin/plugin.json`. Everything, local or referenced, is listed in
  `.claude-plugin/marketplace.json`.
- Nothing project-specific in a plugin. Anything that varies by repository —
  a project id, a bucket name, a paper's directory layout — is read from the
  consuming repository at run time, never baked into the plugin. A plugin's
  directory is a cache shared by every project on the machine, so state stored
  beside a script is inherited by whichever repo runs next.
- Public on purpose: a cloud session's GitHub access is scoped to the
  repository it was launched from, so a private marketplace would be
  unreachable from the projects that need it. Nothing here should ever contain
  a credential.

### Referenced plugins

Third-party entries carry a `source` pointing at the upstream GitHub repository
instead of a copy under `plugins/`. Nothing is vendored, so upstream fixes arrive
without a sync commit here and their licenses stay with their authors.

The tradeoff is that upstream can change under you. Entries are deliberately left
unpinned to keep them current; to freeze one, add a `sha` beside its `repo` and
bump it deliberately:

```json
"source": { "source": "github", "repo": "blader/humanizer", "sha": "<commit>" }
```

Upstream repositories that are already packaged as plugins are referenced as-is.
Those that are only a bare `SKILL.md` at the repository root work the same way —
Claude Code scans the plugin root, so no `strict` or `skills` override is needed
in the entry.

Validate after editing the manifest, which also catches a plugin whose upstream
layout has drifted:

```bash
claude plugin validate . --strict
```

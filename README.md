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

Four entries, each doing a job none of the others does: de-AI a general document,
de-AI a manuscript, draft a paper, prepare a submission. That non-overlap is
maintained by hand — see [Pruning](#pruning) for what was cut and why. Star counts
are from August 2026 and are only a rough proxy for how well-exercised each one
is.

| Plugin | Invoke as | Job | Upstream | Stars | Always-on |
| :-- | :-- | :-- | :-- | --: | --: |
| `humanizer` | `humanizer` | General de-AI | [blader/humanizer](https://github.com/blader/humanizer) | ~35.8k | ~170 tok |
| `academic-humanizer` | `academic-humanizer` | Manuscript de-AI | [AIScientists-Dev/academic-humanizer](https://github.com/AIScientists-Dev/academic-humanizer) | ~958 | ~182 tok |
| `paper-writing-skill` | `paper-writing` | Drafting and audit | [SNL-UCSB/paper-writing-skill](https://github.com/SNL-UCSB/paper-writing-skill) | ~163 | ~275 tok |
| `academic-writing-skills` | `cover-letter`, `bib-search-citation` | Submission | [bahayonghang/academic-writing-skills](https://github.com/bahayonghang/academic-writing-skills) | ~416 | ~598 tok |

All are MIT licensed except `academic-writing-skills` — see
[Licensing](#licensing). Several answer to a name that differs from the plugin's,
hence the second column.

- **humanizer** — rewrites against the 33 patterns in Wikipedia's "Signs of AI
  writing", in two passes, and can calibrate to a voice profile built from your
  own earlier writing. Fires only on clusters of tells, treats neutral register as
  correct rather than suspect, and leaves citations alone, which is what makes it
  the safer general tool to have installed near technical text.
- **academic-humanizer** — the same de-AI pass with scholarly convention held
  intact: citations, data, and numbers are left alone, and claims are pinned to
  the strength the evidence supports (`prove` becomes `show empirically`). Has an
  NSF/NIH proposal mode.
- **paper-writing-skill** — a five-stage pipeline (brainstorm, architect, draft,
  integrate, compress) with per-section rhetorical moves, a style audit on every
  edit, and an independent red-team pass. Calibrated for systems and ML venues.
- **academic-writing-skills** — submission-time work: `cover-letter` drafts the
  submission letter, `bib-search-citation` searches for and formats citations.
  Upstream ships four more skills — a prose polisher, a submission audit, a
  Chinese thesis skill, and a Typst one — which this entry deliberately does not
  load.

## Pruning

A skill fires on the `description` in its own `SKILL.md` frontmatter. That text
belongs to the upstream author, and nothing in a marketplace entry overrides it:
the entry's `description` is plugin-level metadata, and neither it nor
`plugin.json` can rewrite a skill's trigger. Narrowing a trigger means forking the
`SKILL.md`, which means vendoring, which costs the things
[referencing](#referenced-plugins) buys — and for `academic-writing-skills` would
mean redistributing work whose author never granted redistribution.

So overlap is removed by dropping things instead. Two levers, both used here:
whole entries, and individual skills within an entry via its `skills` array.

### What was cut

| Cut | Cost | Because |
| :-- | --: | :-- |
| `stop-slop` | ~60 tok | Its trigger — "drafting, editing, or reviewing text" — is most editing requests in any repository, and it is the most damaging thing here to fire on a manuscript. `humanizer` does the same job more carefully. |
| `academic-writing-agents` | ~702 tok | A 12-agent bundle duplicating prose, review, bibliography, and drafting, each already covered by a cheaper specialist. It also auto-activates on `.tex`, which is the uncontrolled-firing problem in its purest form. |
| `latex-paper-en` | — | Prose polishing, which is `academic-humanizer`'s job. |
| `paper-audit` | — | Reviewer-style critique, which is `paper-writing-skill`'s red-team pass. |

What is left costs roughly 1.2k tokens with everything enabled, down from 2.4k,
and no two entries claim the same work.

Nothing is lost permanently — restoring any of these is re-adding its entry, or
its path to a `skills` array. Worth knowing what the cuts were about, though:

**The general and academic passes genuinely contradict each other.** `stop-slop`
required that "every sentence needs a human subject doing something, no passive
constructions" and said to "skip softening." `academic-humanizer` holds the
opposite for manuscripts: evidence-tied hedging is "correct and required" — keep
`suggests`, keep `is consistent with` — passive is "fine when the actor is
irrelevant," and `we` is standard. Both are right for their own domain, but
applied to a paper the general rule does real damage: strip the hedge from *these
results suggest X* and you are left with *X*, a stronger claim than the data
supports. That is a reviewer problem, not a style problem. `academic-humanizer`'s
own documentation puts it plainly — "a general humanizer flattens legitimate
scholarly constructs."

**Compounding passes flatten prose.** Two skills firing in sequence means the
second edits the first's output. Each removes what it was built to remove, and
nothing puts the variation back.

`humanizer` and `academic-humanizer` still overlap by design, since they are the
same job for different registers. Hence the one rule that survives pruning:
**one de-AI pass per repository, chosen deliberately.** The drafting and
submission tools compose fine alongside it.

### Per project

| Repository | Enable |
| :-- | :-- |
| Paper or thesis (LaTeX) | `academic-humanizer` + `paper-writing-skill` |
| Paper nearing submission | add `academic-writing-skills`, then disable it again |
| Grant or proposal | `academic-humanizer` |
| README, docs, blog, email | `humanizer` |
| Code repository | none |

Concretely, in a paper repository's `.claude/settings.json`:

```json
{
  "enabledPlugins": {
    "academic-humanizer@agent-tools": true,
    "paper-writing-skill@agent-tools": true
  }
}
```

Two habits worth having. Enabling a skill only makes it *available* — you can
still name it directly ("use academic-humanizer on this section") to force the
choice when more than one could plausibly fire. And run these with the draft
committed first: they rewrite prose in place, and the diff is the only practical
way to see what a pass actually changed.

Check what a repository is actually carrying with `claude plugin list` or
`/plugin`.

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

### Licensing

Referencing rather than vendoring keeps this simple: nothing here is a copy of
anyone else's work, so this repository does not redistribute it and cannot
relicense it. Copyright stays with each upstream author, their terms reach the
person installing the plugin directly, and a licence chosen for this repository
would cover only what is actually in it — the manifest, the README, and
`plugins/`.

Three of the four writing entries are MIT. `academic-writing-skills` is not, and
is worth knowing about:

- It has no `LICENSE` file. The only stated terms are a line in its README —
  "Academic Use Only — Not for commercial use."
- Absent a licence file, the default is ordinary copyright, and that README line
  is a narrow grant rather than a redistribution licence.

Referencing it is unaffected, since Claude Code clones it from its own repository
at install time. Academic use is squarely within what the author permits.
Vendoring a copy into `plugins/` is the thing to avoid: that would be
redistribution, which nothing upstream clearly grants. The `license` field on
that entry records the restriction so it is visible before installing.

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
the last four know what a manuscript is. Star counts are from August 2026 and
are only a rough proxy for how well-exercised each one is.

| Plugin | Invoke as | Upstream | Stars | Always-on |
| :-- | :-- | :-- | --: | --: |
| `humanizer` | `humanizer` | [blader/humanizer](https://github.com/blader/humanizer) | ~35.8k | ~170 tok |
| `stop-slop` | `stop-slop` | [hardikpandya/stop-slop](https://github.com/hardikpandya/stop-slop) | ~15.7k | ~60 tok |
| `academic-humanizer` | `academic-humanizer` | [AIScientists-Dev/academic-humanizer](https://github.com/AIScientists-Dev/academic-humanizer) | ~958 | ~182 tok |
| `paper-writing-skill` | `paper-writing` | [SNL-UCSB/paper-writing-skill](https://github.com/SNL-UCSB/paper-writing-skill) | ~163 | ~275 tok |
| `academic-writing-agents` | `academic` | [andrehuang/academic-writing-agents](https://github.com/andrehuang/academic-writing-agents) | ~161 | ~702 tok |
| `academic-writing-skills` | 4 skills, named below | [bahayonghang/academic-writing-skills](https://github.com/bahayonghang/academic-writing-skills) | ~416 | ~1,059 tok |

All are MIT licensed except `academic-writing-skills` — see
[Licensing](#licensing). Two answer to a name that differs from the plugin's,
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
  activates on `.tex` files and will rewrite, not just report.
- **academic-writing-skills** — the submission end rather than the drafting end.
  Four separate skills: `latex-paper-en` polishes an English LaTeX paper,
  `paper-audit` runs a reviewer-style critique before you submit, `cover-letter`
  drafts the submission letter, and `bib-search-citation` handles bibliography
  search. Upstream also ships a Chinese-thesis skill (GB/T 7714) and a Typst
  skill, which this entry does not load; to pick them up, add their paths to the
  entry's `skills` array.

## Choosing one

Enabling everything at once is the one configuration that reliably makes writing
worse. Two reasons, and they are separate problems.

### They contradict each other on academic prose

General de-AI tools and academic convention disagree about the same constructs,
not by accident but by design. `stop-slop` requires that "every sentence needs a
human subject doing something, no passive constructions" and says to "skip
softening." `academic-humanizer` states the opposite for manuscripts:
evidence-tied hedging is "correct and required" — keep `suggests`, keep `is
consistent with` — passive is "fine when the actor is irrelevant," and `we` is
standard.

Both are right for their own domain. Applied to a paper, though, the general rule
does real damage: stripping the hedge from *these results suggest X* leaves *X*,
which is not a tightened sentence but a stronger claim than the data supports.
That is a reviewer problem, not a style problem. `academic-humanizer`'s own
documentation is blunt about it — "a general humanizer flattens legitimate
scholarly constructs."

`humanizer` is the safer of the two general tools on technical text: it fires
only on clusters of tells, treats neutral register as correct rather than
suspect, and does not flag citations. `stop-slop` is the one to keep away from a
manuscript.

### Their triggers overlap

Several of these describe themselves in nearly the same terms — `stop-slop`
answers to "drafting, editing, or reviewing text," which is most editing requests
in any repository. With four or five enabled, which one fires is not something
you control, and two firing in sequence means the second edits the first's
output. Compounding passes flatten voice: each removes what it was built to
remove, and nothing puts back the variation.

So: **one de-AI pass per repository, chosen deliberately.** The drafting and
audit tools compose fine alongside it, since they do a different job.

### Per project

| Repository | Enable | Why |
| :-- | :-- | :-- |
| Paper or thesis (LaTeX) | `academic-humanizer` + `paper-writing-skill` | Hedging and passive survive; the pipeline handles structure |
| Paper nearing submission | add `academic-writing-skills` | Reviewer-style audit and cover letter, then disable it again |
| Heavy `.tex` review round | `academic-writing-agents` alone | 12 agents already cover prose, math, figures, and bibliography |
| Grant or proposal | `academic-humanizer` | Has an explicit NSF/NIH mode |
| README, docs, blog, email | `humanizer` **or** `stop-slop` | Pick one — `stop-slop` if you want it cheap and blunt |
| Code repository | none | Nothing here helps with code |

Concretely, in a paper repository's `.claude/settings.json`:

```json
{
  "enabledPlugins": {
    "academic-humanizer@agent-tools": true,
    "paper-writing-skill@agent-tools": true
  }
}
```

Two further habits worth having. Enabling a skill only makes it *available* — you
can still name it directly ("use academic-humanizer on this section") to force a
specific one when several could plausibly fire. And run these on a branch or with
the draft committed first: they rewrite prose in place, and the diff is the only
practical way to see what a pass actually changed.

Cost is the other reason to be selective. Enabling every writing entry costs
roughly 2.4k tokens of always-on context in every session, before you have asked
for anything; `academic-writing-skills` and `academic-writing-agents` are three
quarters of that. Check what a given repository is actually carrying with
`claude plugin list` or `/plugin`.

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

Five of the six writing entries are MIT. `academic-writing-skills` is not, and is
worth knowing about:

- It has no `LICENSE` file. The only stated terms are a line in its README —
  "Academic Use Only — Not for commercial use."
- Absent a licence file, the default is ordinary copyright, and that README line
  is a narrow grant rather than a redistribution licence.

Referencing it is unaffected, since Claude Code clones it from its own repository
at install time. Academic use is squarely within what the author permits.
Vendoring a copy into `plugins/` is the thing to avoid: that would be
redistribution, which nothing upstream clearly grants. The `license` field on
that entry records the restriction so it is visible before installing.

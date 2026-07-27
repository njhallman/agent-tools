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

### overleaf-tracked-changes

Reads and edits Overleaf documents as real accept/reject suggestions from a
terminal session, with no browser. Overleaf's track-changes state exists only
inside Overleaf, so LaTeX pushed through its git sync always arrives as a plain
update; this drives the realtime protocol directly instead.

Needs an `overleaf_session2` cookie in `$OVERLEAF_SESSION` and a per-repository
`.claude/overleaf-project-id`. The skill's own documentation covers both, along
with the protocol details — most of which are silent failures rather than
errors, and are written down so they don't have to be rediscovered.

## Conventions

- One directory per plugin under `plugins/`, each with its own
  `.claude-plugin/plugin.json`, listed in `.claude-plugin/marketplace.json`.
- Nothing project-specific in a plugin. Anything that varies by repository —
  a project id, a bucket name, a paper's directory layout — is read from the
  consuming repository at run time, never baked into the plugin. A plugin's
  directory is a cache shared by every project on the machine, so state stored
  beside a script is inherited by whichever repo runs next.
- Public on purpose: a cloud session's GitHub access is scoped to the
  repository it was launched from, so a private marketplace would be
  unreachable from the projects that need it. Nothing here should ever contain
  a credential.

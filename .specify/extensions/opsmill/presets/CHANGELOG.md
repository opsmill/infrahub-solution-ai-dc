# Changelog — preset collection

Release history for the `presets/` directory, taken as a unit.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this collection adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-06-03

### Added
- **`reconcile-opsmill`** (preset version `1.1.0`) — first release, versioned to the preset collection (there is no released `1.0.0`).
  Spec-kit preset (`schema_version: "1.0"`,
  `requires.speckit_version: ">=0.8.0"`) that declares one command
  override under `provides.templates`: `type: command`,
  `name: speckit.reconcile.run`,
  `file: commands/speckit.reconcile.run.md`,
  `replaces: speckit.reconcile.run` (default `replace` strategy).
  Installable independently via:

  ```bash
  git clone https://github.com/opsmill/opsmill-speckit
  specify preset add --dev opsmill-speckit/presets/reconcile-opsmill
  ```

  Overrides `speckit.reconcile.run` — the drift-fixing command of the
  [stn1slv/spec-kit-reconcile](https://github.com/stn1slv/spec-kit-reconcile)
  extension — so OpsMill can adapt the command body to its repo
  structure without forking the upstream extension. The override only
  registers when the `reconcile` extension is installed in the
  consumer repo (`.specify/extensions/reconcile/`).

  OpsMill adaptations over the upstream body (one commit each in the
  preset's git history):
  - Remediation tasks placed in `## Phase <N>:` blocks (new
    `## Phase <max+1>: Remediation — Gap Report` when no phase fits)
    instead of upstream's `## Remediation: Gaps` heading, which the
    `taskstoissues-jira` fan-out would silently skip.
  - `[P]` restored to the core spec-kit meaning ("can run in
    parallel") instead of upstream's priority/urgency flag.
  - Compliance gate additionally loads MUSTs from `dev/guidelines/`
    and decisions from `dev/adr/` alongside
    `.specify/memory/constitution.md`.
  - Sync Impact Report's Next Step is Jira-aware when `dev/jira.yml`
    exists, warning against wholesale `/speckit.taskstoissues`
    re-runs.

### Provenance
`reconcile-opsmill` derives from the upstream `commands/reconcile.md`
(stn1slv/spec-kit-reconcile @ `886f1dd`): the verbatim lift is this
preset's baseline commit in git history, and the first released version
is `1.1.0`, carrying the OpsMill adaptations listed above. Upstream is MIT-licensed by Stanislav
Deviatov; the license ships in `reconcile-opsmill/LICENSE`.

## [1.0.0] - 2026-05-20

### Added
- **`taskstoissues-jira`** (preset version `1.0.0`) — initial release of
  the collection's first preset. Spec-kit preset
  (`schema_version: "1.0"`, `requires.speckit_version: ">=0.8.0"`) that
  declares one command override under `provides.templates`:
  `type: command`, `name: speckit.taskstoissues`,
  `file: commands/speckit.taskstoissues.md`,
  `replaces: speckit.taskstoissues` (default `replace` strategy).
  Installable independently via:

  ```bash
  specify preset add taskstoissues-jira \
    --from https://github.com/opsmill/opsmill-speckit/archive/refs/heads/main.zip \
    --subdir presets/taskstoissues-jira
  ```

  Overrides the native `/speckit.taskstoissues` to fan `tasks.md` out
  into Jira issues under a single Epic — one issue per `## Phase N:`
  block, with `Blocks` links derived from `T<NNN>` mentions
  (transitively reduced). Talks to Atlassian through the Atlassian MCP.
  Project config lives at `dev/jira.yml` in the consumer repo; the
  assignee is the user authenticated to the Atlassian MCP (resolved via
  `atlassianUserInfo`). See
  [`taskstoissues-jira/README.md`](taskstoissues-jira/README.md) for the
  full configuration model and behavior.

### Provenance
`taskstoissues-jira` is ported from the Infrahub preset in
[opsmill/infrahub#9208](https://github.com/opsmill/infrahub/pull/9208).
Generalized for cross-repo reuse:
- Project key + Epic key regex driven by `default_project_key` from
  config rather than hardcoded `IFC`.
- Custom field IDs reduced to placeholders (`customfield_XXXXX`);
  operator resolves real IDs via `getJiraIssueTypeMetaWithFields`.
- Preset id renamed from `infrahub` to `taskstoissues-jira` so the
  install path reads as a portable Jira-flavored override of
  `speckit.taskstoissues` rather than a single-product preset.

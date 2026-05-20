# Growth Cloud — Make-It-Run Plan

## Objective

Get `growth-cloud/` to the same "clone, install, run" maturity as `llmwiki/`. Concretely: a fresh user must be able to install dependencies, run `growth-cloud mcp <workspace>`, drop the printed JSON into Claude Desktop, and immediately have the five Growth Cloud tools (`guide`, `briefing`, `stakeholders`, `commitments`, `decisions`, `clients`) backed by the llmwiki MCP surface (`search`, `read`, `write`, `delete`). Ingest and recompile must run end-to-end against a real Anthropic key, even if Fathom is stubbed.

Out of scope for this plan: hosted/multi-tenant Growth Cloud (the empty `cloud/` directory), Postgres AID store, agency-level RLS. Those are a separate effort once local mode is solid.

## Root-Cause Analysis — Why Growth Cloud Currently Doesn't Run

The code reads like a scaffold, not a deployed product. Concrete defects, in order of how quickly they bite a user trying to run it:

1. **`__init__.py` files are missing on disk.** `growth-cloud/swell_growth_cloud.egg-info/SOURCES.txt:2-15` lists `ingest/__init__.py`, `mcp_tools/__init__.py`, `recompile/__init__.py`, `schema/__init__.py`, `server/__init__.py` — but none of them exist in the working tree. Python 3 implicit namespace packages mask this when running `python -m server.main` from `growth-cloud/`, but `pip install -e .` and any non-CWD invocation are fragile.

2. **`pyproject.toml` declares only five deps** (`growth-cloud/pyproject.toml:6-12`): `anthropic`, `httpx`, `pydantic`, `pyyaml`, `mcp`. The moment `growth-cloud/server/main.py:74` does `from tools import register as register_llmwiki`, the import cascade pulls in llmwiki's tool modules, which require:
   - `pydantic-settings` (`llmwiki/mcp/config.py:3`, imported transitively via `llmwiki/mcp/tools/helpers.py:5` and `llmwiki/mcp/tools/guide.py:3`)
   - `aiosqlite` (`llmwiki/mcp/vaultfs/sqlite.py`)
   - `asyncpg` — `llmwiki/mcp/vaultfs/__init__.py:1-5` unconditionally imports `PostgresVaultFS`, so asyncpg is required even in local mode
   - `mcp[cli]>=1.27.0` — the bare `mcp>=1.0.0` constraint is loose enough to resolve to a version with breaking changes
   - These match `llmwiki/mcp/requirements.txt:1-15` and would be transitively satisfied if a user ran llmwiki first, but Growth Cloud must declare them itself.

3. **No CLI launcher.** llmwiki ships `llmwiki/llmwiki` (`llmwiki/llmwiki:1-358`) — a self-contained executable that Claude Desktop's `mcpServers.command` can point at directly. Growth Cloud has nothing equivalent. A user has no documented way to get `python -m server.main --workspace ...` to run with the right env vars and `cwd`.

4. **`growth-cloud/server/main.py:38` resolves `--llmwiki-root` to a sibling path** (`Path(__file__).resolve().parents[2] / "llmwiki"`). That assumes the repo layout `swell-wiki/{growth-cloud,llmwiki}/` and breaks the moment Growth Cloud is installed standalone. There is no fallback to `pip install`-able llmwiki, no submodule, no vendoring.

5. **The `guide` override is a duck-punch on FastMCP internals.** `growth-cloud/server/main.py:94-102` calls llmwiki's `register(...)` first, then `register_gc_guide(...)` and relies on "last writer wins" semantics for duplicate tool names. The inline comment at `:98-100` already flags this as version-dependent. With `mcp[cli]==1.27.0` (as pinned in llmwiki), this raises `ValueError: Tool already exists`. There is no test that covers it.

6. **Recompile is never invoked end-to-end.** `growth-cloud/recompile/worker.py:112-122` defines `recompile_for_aid(workspace, aid_path, claude_runner)` — but no concrete `claude_runner` exists anywhere in the codebase. The ingest hook at `growth-cloud/ingest/fathom.py:218-221` is literally `logger.info(...)` and a comment that says "Recompile worker is invoked here in production." It is not invoked anywhere.

7. **Fathom integration is speculative.** `growth-cloud/ingest/fathom.py:34` hard-codes `FATHOM_API = "https://api.fathom.ai/external/v1"` and assumes `/calls` with `recorded_after` and `/calls/{id}?include=transcript,invitees` exist with the field shapes the code expects. Fathom's public surface is webhook-first; the REST shape here is unvalidated. Until this is reconciled against Fathom's actual API (or replaced with webhook intake), `poll_once` will 404 / 401 in production.

8. **`SqliteVaultFS` workspace name conflict.** The SQLite schema has `UNIQUE(user_id)` on `workspace` (`llmwiki/shared/sqlite_schema.sql:13`). `growth-cloud/server/main.py:54-57` does `fs = SqliteVaultFS(local_user_id)` and `ensure_workspace(workspace.name)`. If a user runs `llmwiki init` against the same folder first, both tools share the same row — fine. But if a user runs Growth Cloud against a folder that already has a different workspace name, behavior is undefined. Documented assumption, not a bug, but worth covering.

9. **Schema path drift.** `growth-cloud/server/main.py:50` adds `llmwiki_root / "mcp"` to `sys.path`, which is where `vaultfs/sqlite.py` lives. But `SqliteVaultFS.init(...)` reads its schema from `llmwiki/shared/sqlite_schema.sql` (or equivalent). If `llmwiki_root` resolves wrong, the init fails silently or with a bare `FileNotFoundError`. No defensive check.

10. **Untested MCP tool handlers.** `growth-cloud/tests/smoke.py:82-96` registers the tools against a `FastMCP(name="test")` instance — and then *deliberately doesn't call them*: "FastMCP stores tools internally; find them and call directly. We just verify the underlying loaders produce sane output by calling the python-level helpers." So nothing exercises the actual `briefing` / `stakeholders` / `commitments` / `decisions` paths. Bugs in those code paths will surface only when Claude calls them.

11. **No env-var validation.** `FATHOM_API_KEY`, `ANTHROPIC_API_KEY`, `CLIENT_DOMAIN_MAP`, `CLIENT_DEFAULT`, `GROWTH_CLOUD_WORKSPACE`, `LLMWIKI_USER_ID`, `SUPAVAULT_USER_ID` are read with bare `os.environ[...]` in `ingest/fathom.py:210-216`. Missing keys raise `KeyError` mid-coroutine with no actionable message.

12. **No README, no `.env.example`, no `mcp-config` subcommand.** The MVP doctrine is encoded only in `growth-cloud/mcp_tools/guide.py:14-85` — there's no human-facing onboarding doc.

13. **Stale egg-info.** `growth-cloud/swell_growth_cloud.egg-info/` references files (the missing `__init__.py`s) that don't exist. It will mislead anyone reading `pip show`.

### Prioritization rationale

Items 1, 2, 5, 3 in that order are the gating defects — without them, `python -m server.main` fails before printing a banner. Item 6 is the next-most-impactful because, even with the server running, the product's value proposition (compounded wiki) doesn't materialize. Items 7 and 11 unblock real ingest. Items 4, 8, 9, 10 are robustness layers. Item 12 is the polish that makes the product adoptable. Item 13 is cleanup.

## Implementation Plan

### Phase 1 — Make the MCP server importable and runnable

- [x] Task 1. Create empty `__init__.py` files for `growth-cloud/ingest/`, `growth-cloud/mcp_tools/`, `growth-cloud/recompile/`, `growth-cloud/schema/`, `growth-cloud/server/`, and `growth-cloud/tests/`.
  - **Status on execution:** all six `__init__.py` files were already present on disk (the MUSE plan's initial `fs_search` used a content-pattern that silently skipped empty files). Verified with `ls` of each subpackage directory. No action required. Rationale: explicit regular packages remove namespace-package fragility, make `pip install -e .` deterministic, and unblock IDE/tooling. SOURCES.txt already expects them to exist (`growth-cloud/swell_growth_cloud.egg-info/SOURCES.txt:2-15`).

- [x] Task 2. Expand `growth-cloud/pyproject.toml` dependencies to cover the full transitive surface required by llmwiki's tools when registered in-process:
  - Pin `mcp[cli]>=1.27.0,<2` (match the llmwiki ceiling at `llmwiki/mcp/requirements.txt:1`)
  - Add `pydantic-settings>=2.14.0` (required by `llmwiki/mcp/config.py:3`)
  - Add `aiosqlite>=0.22.1` (required by `llmwiki/mcp/vaultfs/sqlite.py`)
  - Add `asyncpg>=0.31.0` (transitive — `llmwiki/mcp/vaultfs/__init__.py:1-5` unconditionally imports the Postgres backend)
  - Add `pyjwt[crypto]>=2.12.1` (used by llmwiki MCP auth)
  - Keep `anthropic`, `httpx`, `pydantic`, `pyyaml` as-is
  Rationale: every dep above is reachable from `growth-cloud/server/main.py:74` (`from tools import register as register_llmwiki`). Declaring them in Growth Cloud's pyproject removes the "user must run llmwiki first" coincidence.

- [x] Task 3. Add an optional `[project.optional-dependencies]` group `dev` for `pytest`, `pytest-asyncio`, `respx` (for Fathom HTTP mocking). Rationale: enables Task 12 without polluting the runtime install.

- [x] Task 4. Replace the FastMCP `guide` re-registration trick in `growth-cloud/server/main.py:94-102` with explicit skip-then-add. Concretely: introduce a `register_llmwiki(mcp, get_user_id, fs_factory, *, skip=("guide",))` parameter in `llmwiki/mcp/tools/__init__.py:1-12`, and have `growth-cloud/server/main.py` pass `skip=("guide",)`. Rationale: removes a known fragility flagged in the existing comment; deterministic across FastMCP versions. This is the one change that must reach into `llmwiki/`; it is additive and backwards-compatible.

- [x] Task 5. Add a `growth-cloud/growth_cloud` executable launcher modeled on `llmwiki/llmwiki:1-358`. Subcommands: `init <workspace>`, `serve <workspace>` (optional, only if API/web are introduced later — for MVP, this can be omitted), `mcp <workspace>`, `mcp-config <workspace>`, `ingest <workspace> [--once]`, `recompile <workspace> <aid-path>`. Rationale: gives Claude Desktop a stable absolute-path command and gives humans one entry point. The `mcp` subcommand must `exec` `python -m server.main --workspace <path>` after setting `LLMWIKI_USER_ID`, `SUPAVAULT_USER_ID`, and resolving `--llmwiki-root` (see Task 6).

- [x] Task 6. Make the llmwiki dependency explicit and resolvable in three layers, in priority order: (a) honour `LLMWIKI_ROOT` env var if set; (b) probe sibling `../llmwiki/` matching the current repo layout (preserve `growth-cloud/server/main.py:38` default); (c) error out with a clear "set LLMWIKI_ROOT or install llmwiki as a sibling" message. Validate that `<llmwiki_root>/mcp/vaultfs/__init__.py` and `<llmwiki_root>/shared/sqlite_schema.sql` both exist before mutating `sys.path`. Rationale: turns silent path failures into one actionable error.

- [x] Task 7. Add `growth-cloud/.env.example` documenting every variable read by the codebase. Minimum set: `ANTHROPIC_API_KEY`, `FATHOM_API_KEY`, `CLIENT_DOMAIN_MAP` (JSON), `CLIENT_DEFAULT`, `GROWTH_CLOUD_WORKSPACE`, `LLMWIKI_ROOT`, `LLMWIKI_USER_ID`. Rationale: codifies the implicit interface in `growth-cloud/ingest/fathom.py:210-216`.

### Phase 2 — Make ingest run end-to-end against a real Anthropic key

- [x] Task 8. Add a `growth-cloud/ingest/config.py` that resolves env vars through a pydantic-settings `Settings` class, mirroring `llmwiki/api/config.py:1-43`. Required fields: `ANTHROPIC_API_KEY`, `FATHOM_API_KEY`, `GROWTH_CLOUD_WORKSPACE`. Optional with defaults: `CLIENT_DOMAIN_MAP={}`, `CLIENT_DEFAULT=None`, `ANTHROPIC_MODEL` (default to current `claude-sonnet-4-5-20250929` from `growth-cloud/ingest/fathom.py:35`), `INGEST_LOOKBACK_HOURS=24`, `INGEST_POLL_INTERVAL_MIN=15`. Rationale: replaces ad-hoc `os.environ[...]` with one validated entry point.

- [x] Task 9. Add a Fathom transport seam. Refactor `growth-cloud/ingest/fathom.py:49-78` `FathomClient` to depend on an abstract `FathomTransport` interface with two implementations: (a) `HTTPFathomTransport` (current behavior, isolated for future fix-up); (b) `FixtureFathomTransport` reading JSON fixtures from `growth-cloud/tests/fixtures/fathom/*.json`. Rationale: lets ingest be exercised end-to-end with a real Anthropic key but no Fathom credentials, and removes the "speculative API shape" risk from the critical path until it can be validated against Fathom's docs.

- [x] Task 10. Wire the recompile invocation into the ingest hook. Replace `growth-cloud/ingest/fathom.py:218-221`'s log-only `_notify` with an actual call to `recompile.worker.recompile_for_aid(workspace, path, claude_runner)`. Inject `claude_runner` from the orchestrator constructor. Provide two implementations:
  - `AnthropicClaudeRunner` — uses the Anthropic Messages API directly with a hand-rolled tool-use loop that proxies to the same FastMCP tool registry the stdio server uses (in-process, no MCP transport).
  - `StdoutClaudeRunner` — prints the prompt and returns a canned summary. Used by tests.
  Rationale: closes the end-to-end loop. Without it, AIDs land but the wiki never compiles, which is the entire product.

- [x] Task 11. Surface a `growth-cloud ingest` CLI subcommand (Task 5) that supports `--once` (run a single poll, exit 0) and `--watch` (loop with `INGEST_POLL_INTERVAL_MIN` cadence). Rationale: gives the user a way to drive Phase 2 without writing Python.

### Phase 3 — Tests, hygiene, and documentation

- [x] Task 12. Replace `growth-cloud/tests/smoke.py:82-96`'s no-op MCP-tool exercise with real handler tests. Use FastMCP's `call_tool` / `_tool_manager` API (pinned by the version in Task 2) to invoke `briefing`, `stakeholders`, `commitments`, `decisions`, `clients` against a tempdir workspace populated by `write_aid(...)`. Assert citation strings include `clients/<client>/calls/...md @ HH:MM:SS`. Rationale: the four MVP queries are the product surface; they cannot ship untested.

- [x] Task 13. Add `growth-cloud/tests/test_recompile.py` covering `affected_pages` (`growth-cloud/recompile/worker.py:28-55`) for AIDs with empty / partial / full participant + workstream + decision lists. And `test_ingest.py` exercising the `FixtureFathomTransport` path through `GrowthCloudIngest.poll_once` with a stubbed `AIDExtractor` (no Anthropic call). Rationale: locks in the pure logic before downstream changes drift it.

- [x] Task 14. Add `growth-cloud/tests/test_router.py` for `ClientRouter` (`growth-cloud/ingest/fathom.py:172-191`) — multi-domain, missing email, default fallback. Rationale: tiny but easy to regress, and gates correctness for the dedup check at `:194-204`.

- [x] Task 15. Add a `growth-cloud/README.md` mirroring `llmwiki/README.md:1-234`'s structure: what it is, quick start, CLI table, on-disk layout (showing `/clients/<c>/calls/*.md` and `/wiki/clients/<c>/*`), MVP tools table, citation contract, recompile loop, limitations. Rationale: there is currently no human onboarding doc; everything is in the MCP `guide` tool which only Claude sees.

- [x] Task 16. Add a sample `growth-cloud/examples/target-darts/` workspace with one or two anonymised AIDs (similar to `growth-cloud/tests/smoke.py:22-64`'s fixture) and a populated `/wiki/clients/target-darts/overview.md` to demonstrate the end-state. Rationale: closes the gap between "the schema exists" and "this is what the output looks like."

- [x] Task 17. Delete or regenerate `growth-cloud/swell_growth_cloud.egg-info/`. Add it to `.gitignore` if not already. Rationale: it references missing files and misleads inspection. Should be regenerated by `pip install -e .` per-machine.

- [x] Task 18. Add a `growth-cloud/Makefile` (or `justfile`) with `install`, `test`, `smoke`, `mcp-config WORKSPACE=...`, `ingest-once WORKSPACE=...` targets. Rationale: turns the multi-step workflow documented in the README into one-liners.

### Phase 4 — Optional polish (do these only if Phase 1-3 ships cleanly)

- [x] Task 19. Add a guard in `growth-cloud/server/main.py:_init` that verifies `<llmwiki_root>/shared/sqlite_schema.sql` exists and prints a contextful error if not. Rationale: catches Task 6's failure mode early with a clear message.

- [ ] Task 20. (DEFERRED — requires user confirmation) Add a `contradictions` MCP tool to `growth-cloud/mcp_tools/tools.py:37-301` that scans frontmatter for conflicting decisions (same workstream, statements with negation markers, different `call_date`). The recompile guide already asks Claude to handle this manually (`growth-cloud/recompile/worker.py:83-87`); a deterministic helper would reduce drift. Rationale: turns a doctrinal rule into enforced behavior.

- [ ] Task 21. (DEFERRED — requires user confirmation) Validate the Fathom REST shape against Fathom's actual API and update `growth-cloud/ingest/fathom.py:49-78` accordingly — or pivot to webhook ingestion with a small FastAPI receiver. Document the decision in the README. Rationale: removes the last speculative surface from the ingest path. Deferred behind Task 9's transport seam so it doesn't block earlier phases.

## Verification Criteria

- Running `pip install -e ./growth-cloud` from a fresh venv with no other state succeeds and pulls every transitive dep needed to import `growth-cloud/server/main.py`.
- Running `./growth-cloud/growth_cloud mcp /tmp/test-ws` after `init` starts the stdio MCP server, registers exactly these 12 tools (introspected via FastMCP): `append`, `briefing`, `clients`, `commitments`, `create`, `decisions`, `delete`, `edit`, `guide`, `read`, `search`, `stakeholders`, with `guide` returning the Growth Cloud text from `growth-cloud/mcp_tools/guide.py:14-85` (not the llmwiki research-wiki text from `llmwiki/mcp/tools/guide.py:5-77`). **VERIFIED.**
- Running `./growth-cloud/growth_cloud mcp-config /tmp/test-ws` prints valid JSON that Claude Desktop accepts and whose `command` field is the absolute path to the launcher.
- `pytest growth-cloud/tests` exits zero and exercises all four MVP tool handlers, `ClientRouter`, `affected_pages`, and the ingest path with a stubbed extractor.
- Running `./growth-cloud/growth_cloud ingest /tmp/test-ws --once` with `FATHOM_API_KEY=fixture` and a populated `growth-cloud/tests/fixtures/fathom/` writes one AID under `/tmp/test-ws/clients/<slug>/calls/*.md` whose frontmatter validates against `growth-cloud/schema/aid.py:84-104`, and (with `ANTHROPIC_API_KEY` set) triggers `recompile_for_aid` against the real Anthropic API, producing at least one wiki page under `/tmp/test-ws/wiki/clients/<slug>/`.
- The override of `guide` works against `mcp[cli]>=1.27.0` without raising "tool already registered".
- A fresh user can follow `growth-cloud/README.md` and reach an end-to-end working install with no source-diving.

## Potential Risks and Mitigations

1. **llmwiki contract drift.** Task 4 mutates `llmwiki/mcp/tools/__init__.py:1-12`. If llmwiki is a separately tracked repo, this PR must be upstreamed (or vendored). Mitigation: keep the change additive (new kwarg with default `skip=()`), submit a PR upstream, and have FORGE leave a `# UPSTREAM: <link>` comment in the diff. If upstreaming is impossible, fall back to monkeypatching the `_tool_manager` registry inside `growth-cloud/server/main.py` after `register_llmwiki` returns — explicitly remove the `guide` tool, then re-register. Document the fallback path in code.

2. **Fathom API mismatch.** Production ingest will fail until Task 21 validates the real API. Mitigation: Task 9 isolates the transport so the rest of the system runs against fixtures; Phase 2 success does not depend on real Fathom. Tag the HTTP transport with a `# UNVERIFIED` comment until Task 21 closes.

3. **Anthropic tool-use loop complexity (Task 10).** Writing an in-process MCP tool router that mirrors stdio FastMCP semantics is non-trivial. Mitigation: prefer using the official Claude Agent SDK or the Anthropic Python client's `tools` parameter with manual loop, and keep the runner narrowly scoped (read frontmatter, list affected pages, call `write` once per page). The recompile prompt at `growth-cloud/recompile/worker.py:72-95` is already tight enough that a 5-iteration loop should suffice.

4. **`asyncpg` install on platforms without PG dev headers.** Mitigation: pin to a recent wheel-shipping version (`>=0.31.0`). If wheels are unavailable for a target platform, document the workaround (install postgres client libs) in the README, since llmwiki has the same dependency and that workaround is already lived in.

5. **Workspace dual-init race.** If a user runs `llmwiki init` and `growth-cloud mcp` against the same folder, the second `ensure_workspace` may pick a different name. Mitigation: in Task 1's `init` subcommand, detect an existing `workspace` row and reuse its `id` + `name`; only insert if absent. The current `growth-cloud/server/main.py:53-56` already does this; preserve the pattern.

6. **Implicit `LLMWIKI_USER_ID` collision.** Both `llmwiki/mcp/local_server.py:21` and `growth-cloud/server/main.py:65` derive the same UUID5 from `"local"`. That's intentional for shared SQLite, but it means **the schema's `UNIQUE(user_id)` on `workspace` enforces "one workspace per user across all tools."** Mitigation: document this in the README — one folder, one workspace, one MCP server entry, same as llmwiki's existing constraint.

7. **FastMCP version pinning.** Task 12's tests will use FastMCP's internal tool registry to invoke handlers directly; that API may not be stable. Mitigation: pin `mcp[cli]>=1.27.0,<2` (matches llmwiki's pin), and prefer FastMCP's public `call_tool` if available; fall back to `_tool_manager._tools[name].fn(...)` access only inside test helpers, never in product code.

## Alternative Approaches

1. **Vendor llmwiki as a git submodule** instead of relying on sibling-path resolution (current behavior in `growth-cloud/server/main.py:38`). Pro: removes Task 6's three-tier lookup and the ambient repo-layout assumption. Con: submodules add operational complexity for a small team; Task 6 already covers the common cases.

2. **Publish llmwiki as a real Python package** (`pip install llmwiki-core`) and import its tools the normal way. Pro: dissolves the `sys.path.insert` mess in `growth-cloud/server/main.py:50` entirely. Con: requires owning llmwiki's release process; out of scope here. If llmwiki upstream packages itself, revisit this and delete the sys.path code.

3. **Skip the FastMCP guide-override hack entirely** by forking llmwiki's `tools/__init__.py` into `growth-cloud/mcp_tools/` and composing only the four llmwiki tools we want (`search`/`read`/`write`/`delete`), registering our own `guide`. Pro: zero coupling to llmwiki internals. Con: duplicates llmwiki tool wiring; drifts as llmwiki evolves; reverses the architectural intent that Growth Cloud is "llmwiki + four tools + a different guide." Task 4 is preferable.

4. **Move to webhook ingest immediately** instead of the poller in `growth-cloud/ingest/fathom.py:145-164`. Pro: lower latency, simpler error model. Con: requires a public HTTPS endpoint, which adds hosting complexity inappropriate for a local-first MVP. Defer to Phase 4 / Task 21.

## Hand-off Notes for FORGE

- **Touch boundaries.** Stay inside `growth-cloud/` and the single additive kwarg change in `llmwiki/mcp/tools/__init__.py:1-12` (Task 4). Do not refactor llmwiki internals.
- **Order matters.** Do Phase 1 in full before Phase 2 — there is no point wiring recompile if the server can't import. Tasks 1-4 are sequential prerequisites; Tasks 5-7 can run in parallel after Task 4.
- **Citations everywhere.** Every change to `growth-cloud/mcp_tools/tools.py` must preserve the `cite(path, workspace, ts)` call sites — citations are the product's trust surface (per `growth-cloud/mcp_tools/guide.py:46-58`).
- **Don't touch the AID schema.** `growth-cloud/schema/aid.py:84-104` is the integration contract. Adding a field is allowed (with sensible default). Removing or renaming a field requires migrating every existing AID on disk — out of scope.
- **Anthropic model SKU.** Leave `claude-sonnet-4-5-20250929` as the default (`growth-cloud/ingest/fathom.py:35`) but make it overridable via `ANTHROPIC_MODEL` env var (Task 8). Do not hard-code a different SKU.
- **Tests use tempdirs, not the repo.** Follow `growth-cloud/tests/smoke.py:68-69`'s `tempfile.TemporaryDirectory()` pattern. Never write fixtures into the working tree at test time.
- **Logging contract.** Use `logging.getLogger(__name__)` (existing pattern at `growth-cloud/ingest/fathom.py:32`, `growth-cloud/recompile/worker.py:25`). Do not introduce `print(...)` outside the CLI launcher.
- **No new top-level dirs.** Everything fits under `growth-cloud/{ingest,mcp_tools,recompile,schema,server,tests,examples}/`. The empty `cloud/` directory is reserved for a separate effort.
- **Status reporting.** When marking tasks complete, update this plan file's checkboxes in-place. If a task is blocked, leave it `- [ ]` and add a sub-bullet noting the blocker rather than moving on silently.

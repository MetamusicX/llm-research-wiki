# `wiki` — the deterministic tooling layer

> *The tool is the hands; the agent is the head.* — the [engram](https://github.com/jeromeetienne/engram) philosophy, adapted here.

The wiki's schema (`CLAUDE.md`) already **specifies** every mechanical check —
broken links, orphans, index drift, missing frontmatter. But running those by
having the *agent* hand-scan every page is slow, token-expensive, and easy to
get wrong. This script moves the mechanical half out of the model into
deterministic Python. The agent keeps the irreducibly semantic work (reading,
synthesising, judging); the tool does the counting.

Idea and structure borrowed from two sibling projects in the same
[Karpathy LLM-wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
lineage: **[engram](https://github.com/jeromeetienne/engram)** (a validator-only
CLI with relative-link resolution) and
**[tome](https://github.com/chicken-noodle-chris/tome)** (a `conventions.toml`
that splits *data-shaped* rules out of the prose schema).

## Usage

```bash
python3 scripts/wiki.py lint                      # full report (error + warn + info)
python3 scripts/wiki.py lint --min-severity warn  # hide info
python3 scripts/wiki.py lint --min-severity error # errors only — the commit gate
python3 scripts/wiki.py lint --type concept       # restrict to one page type
python3 scripts/wiki.py lint --root /path/to/wiki # explicit root (else walks up for conventions.toml)
```

Exit code is **nonzero iff there is an ERROR-tier finding**, so it can gate a
commit or CI run: *"`wiki lint` must pass error-free as the last step of any
wiki-touching task."* No third-party dependencies (stdlib only; ships its own
minimal TOML reader for Python 3.9, and prefers `tomllib`/`tomli` when present).
**An empty wiki lints clean** — a freshly cloned template with no pages yet
reports `0 pages` and exits 0.

## What it checks

| Check | Tier | Meaning |
|---|---|---|
| `frontmatter-missing` / `frontmatter-field` | **error** | no YAML block, or a missing base required field (`title`/`type`/`tags`/`created`/`updated`) |
| `type-unknown` / `type-folder` | **error** | `type:` not in the enum, or disagreeing with the page's folder |
| `link-broken` (into `wiki/**.md`) | **error** | a real knowledge-graph link points at a missing page |
| `frontmatter-type-field` | warn | a per-type field is missing (e.g. a source-note without `author`/`date`/`source-type`) |
| `source-type` | warn | `source-type:` value not in the enum |
| `related-broken` | warn | a `related:` stem resolves to no page |
| `marker-relevance` / `marker-overview` | warn | *(optional)* an epistemic-marker header without its marker — only if enabled in `conventions.toml` |
| `orphan` | warn | a page no other wiki page links to (index/log/README don't count) |
| `oversize` (hard cap) | warn | page longer than the hard cap — consider splitting |
| `link-broken` (into `raw/`) | info | a provenance pointer to immutable source material (often gitignored / absent) |
| `index-drift` | info | a tracked-type page not linked from `index.md` |
| `thin-support` | info | a concept/debate citing fewer than the minimum source-notes |
| `related-missing` / `related-count` | info | concept/author `related:` absent or outside 3–5 |
| `oversize` (soft cap) / `stale` | info | length / staleness nudges |

Link resolution is **relative to each file's own directory**, so it correctly
handles both `index.md` (at root, links as `wiki/concepts/x.md`) and pages
inside `wiki/` (cross-linking as `../concepts/x.md`). Targets are URL-decoded
before the existence check; links inside fenced code blocks and `` `inline code` ``
are ignored (they're examples, not real links). The index and meta-file checks
run only once the wiki has at least one content page.

## Configuration — `conventions.toml`

Data-shaped rules live in `../conventions.toml`: the type enum, required
frontmatter (base + per-type), the folder↔type map, the `source-type` enum,
`related` bounds, size caps, staleness thresholds, the index's tracked types,
and skip-lists. The linter is **schema-agnostic** — it does exactly what that
file says, so the same script serves this template and any specialised fork.
Edit the TOML to retune the checks; keep it in sync with `CLAUDE.md`.

**Epistemic markers are opt-in.** This template ships without them. If you adopt
a provenance-tagging convention (e.g. `[P]` for your own research claims, `[W]`
for the wiki's cross-source synthesis), uncomment the `[markers]` block in
`conventions.toml` and the two marker checks activate.

## Roadmap

The CLI is built as a subcommand seam; `lint` is the first tenant. Natural next
tenants, in rough priority order:

- `wiki move <old> <new>` — rename a page and rewrite every inbound relative link
  (painful by hand because we use relative links, not `[[wikilinks]]`).
- `wiki search <query>` — BM25 over frontmatter + body, an index-fallback for query.
- `wiki whois <name>` — resolve an author name/alias to its page.
- `wiki index` — regenerate / diff `index.md` from page frontmatter.

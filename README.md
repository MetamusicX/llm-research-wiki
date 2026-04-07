# LLM Research Wiki

A personal, LLM-maintained knowledge base for academic research, built on plain markdown files and operated via [Claude Code](https://claude.ai/code).

## Origin

This project implements [Andrej Karpathy's LLM Wiki pattern](https://karpathy.ai/blog/llmwiki.html) (April 2026) — the idea that instead of using RAG to re-derive knowledge from raw documents on every query, an LLM should incrementally build and maintain a **persistent, structured wiki** that compounds over time.

The adaptation was developed by [Paulo de Assis](https://github.com/MetamusicX) in conversation with ChatGPT 5.4 Thinking (for initial design exploration) and Claude Code (for implementation, schema authoring, and the full wiki build). The chain:

1. **Karpathy's post** — the core pattern: raw sources → LLM-maintained wiki → structured queries
2. **Design exploration via ChatGPT 5.4 Thinking** — adapting the pattern to academic research: domain-specific page types, ingest/query/lint workflows, folder conventions
3. **Implementation via Claude Code** — building the full system: `CLAUDE.md` schema with six page templates and three workflows, folder structure, first ingest producing 38 wiki pages in a single pass

## What it does

Every time a source is ingested, Claude reads it, extracts key claims and quotes, and writes or updates markdown pages across the wiki — concept pages, author pages, debate pages, synthesis pages, and source notes. The raw documents are never modified. The wiki is the living layer that accumulates knowledge across all ingested sources.

Over time, the wiki becomes smarter than your memory about connections across your reading.

## Architecture

Three layers:

| Layer | Contents | Who writes it |
|-------|----------|---------------|
| **raw/** | Immutable source documents (articles, books, chapters, notes, transcripts, images) | You |
| **wiki/** | Structured markdown pages (concepts, authors, debates, syntheses, source-notes, projects) | The LLM |
| **schema** | `CLAUDE.md` (operational instructions), `index.md` (master index), `log.md` (change log) | You + the LLM |

## Workflows

The operational logic lives in `CLAUDE.md`. Claude reads it at the start of every session and acts as a dedicated research intelligence agent. Three core workflows:

### INGEST
Drop a source into `raw/`, then say **"ingest [filename]"**. Claude reads it, discusses key takeaways, writes a source note, and updates every concept/author/debate/project page touched by the source. A single ingest typically creates or updates 10–15 wiki pages. Everything is logged in `log.md`.

### QUERY
Ask any research question. Claude checks `index.md` first, reads the relevant wiki pages, and answers from synthesized knowledge — not by re-reading raw sources. If the answer is substantial, Claude offers to save it as a new wiki page.

### LINT
Say **"lint"** to audit the wiki for duplicates, contradictions, orphan pages, stale content, concepts mentioned but lacking pages, and thin source support. Results are presented as a prioritized issues list. Nothing is auto-fixed.

## Folder structure

```
raw/
  articles/   books/   chapters/   notes/   transcripts/   images/   _staging/
wiki/
  concepts/   authors/   debates/   themes/   methods/
  syntheses/   source-notes/   projects/
outputs/
  essays/   slides/   handouts/   tables/
conversations/
archive/
```

## Page types

Six page templates are defined in `CLAUDE.md`, each with YAML frontmatter:

| Type | Location | Purpose |
|------|----------|---------|
| **Source note** | `wiki/source-notes/` | One page per ingested source — summary, key claims, quotes, connections |
| **Concept** | `wiki/concepts/` | One page per concept — definition, key thinkers, related concepts, source support |
| **Author** | `wiki/authors/` | One page per thinker — bio, key works, concepts, relevance |
| **Debate** | `wiki/debates/` | Framed intellectual debates — positions, key texts, current state |
| **Synthesis** | `wiki/syntheses/` | Evolving argumentative overviews across multiple sources |
| **Project** | `wiki/projects/` | Active research or writing projects — concepts, sources, outputs |

## Getting started

1. Clone this repo
2. Open the folder in [Claude Code](https://claude.ai/code) (terminal or VS Code)
3. Edit `CLAUDE.md` to add your own domain context — your research areas, key thinkers, core concepts
4. Write a short research map in your own words (2–3 pages) and save it in `raw/notes/`
5. Say **"ingest raw/notes/your-research-map.md"**
6. Watch the wiki populate with concept pages, author pages, and debate pages from your first source
7. Add real sources one at a time. Supervise the first 5–10 ingests closely.

## Conventions

- **Filenames:** lowercase-kebab-case (`simondon-transduction.md`)
- **YAML frontmatter:** Every page starts with `title`, `type`, `tags`, `created`, `updated`
- **Wiki links:** Relative markdown links (`[Transduction](../concepts/transduction.md)`)
- **Log everything:** Every ingest and change is appended to `log.md`
- **raw/ is immutable:** Source files are never modified after ingest
- **The wiki answers questions, not the raw sources:** Build the wiki so it contains what you need

## Scaling advice

- Start with your own research map as the first ingest — it seeds the wiki with YOUR conceptual framework
- Ingest sources one at a time for the first 10–15 sources — supervise quality
- Don't try to ingest your entire library — only ingest what matters to your active projects
- Use `raw/_staging/` as a holding pen for candidates — review weekly, promote or remove
- Run lint every 10–15 ingests to keep the wiki healthy
- At ~50 sources the wiki becomes a genuine research tool; at ~100 it's indispensable

## Requirements

- [Claude Code](https://claude.ai/code) (terminal or desktop app)
- The `CLAUDE.md` file in the root folder — this is what makes Claude a wiki agent
- No database, no embeddings, no plugins — just markdown files and folders

## Credits

- **Pattern:** [Andrej Karpathy, "LLM Wiki"](https://karpathy.ai/blog/llmwiki.html) (https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) (April 2026)
- **Adaptation and implementation:** [Paulo de Assis](https://github.com/MetamusicX)
- **Design exploration:** ChatGPT 5.4 Thinking (OpenAI)
- **Schema authoring and build:** Claude Code (Anthropic)

## License

MIT

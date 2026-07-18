#!/usr/bin/env python3
"""wiki — the deterministic 'hands' layer for an LLM Research Wiki.

Philosophy (borrowed from engram): the tool is the hands, the agent is the head.
Everything mechanically checkable — link integrity, orphans, index drift, missing
frontmatter, and (optionally) epistemic-register markers — lives here as
deterministic code, so the agent stops hand-scanning every page for it.

The prose schema stays in CLAUDE.md; the data-shaped rules live in conventions.toml.
This linter is schema-agnostic: behaviour is driven entirely by conventions.toml,
so the same script serves both this template and a fully specialised wiki.

Usage:
    python3 scripts/wiki.py lint [--root PATH] [--min-severity error|warn|info] [--type TYPE]

Exit code is nonzero when any ERROR-tier finding is present, so this can gate a
commit or CI ("lint must pass error-free as the last step of any wiki-touching task").
An empty wiki (no pages under wiki/ yet) always lints clean.

Roadmap (not yet implemented — this is the seam to grow the CLI along):
    wiki move <old> <new>   safe rename, rewrite every inbound relative link
    wiki search <query>     BM25 over frontmatter + body
    wiki whois <name>       resolve an author name/alias to its page
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date
from urllib.parse import unquote

# ─────────────────────────────────────────────────────────────────────────────
# Config loading (tomllib / tomli if present, else a minimal parser for our file)
# ─────────────────────────────────────────────────────────────────────────────

def _load_toml(path):
    try:
        import tomllib  # Python 3.11+
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except ModuleNotFoundError:
        pass
    try:
        import tomli  # optional backport
        with open(path, "rb") as fh:
            return tomli.load(fh)
    except ModuleNotFoundError:
        pass
    return _mini_toml(path)


def _mini_toml(path):
    """Tiny TOML reader for conventions.toml only: [tables], scalars, 1-line arrays."""
    data, cur = {}, None
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                cur = data.setdefault(line[1:-1].strip(), {})
                continue
            if "=" not in line or cur is None:
                continue
            key, val = line.split("=", 1)
            cur[key.strip()] = _mini_val(_strip_toml_comment(val).strip())
    return data


def _strip_toml_comment(s):
    """Drop a trailing ` # comment`, but not a `#` inside a quoted string."""
    out, q = [], None
    for ch in s:
        if q:
            out.append(ch)
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out)


def _mini_val(v):
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [_mini_val(x.strip()) for x in inner.split(",")]
    if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
        return v[1:-1]
    if v in ("true", "false"):
        return v == "true"
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    return v


# ─────────────────────────────────────────────────────────────────────────────
# Findings
# ─────────────────────────────────────────────────────────────────────────────

SEV = {"error": 3, "warn": 2, "info": 1}


class Finding:
    __slots__ = ("sev", "code", "relpath", "line", "msg")

    def __init__(self, sev, code, relpath, msg, line=0):
        self.sev, self.code, self.relpath, self.line, self.msg = sev, code, relpath, line, msg

    def loc(self):
        return f"{self.relpath}:{self.line}" if self.line else self.relpath


# ─────────────────────────────────────────────────────────────────────────────
# Frontmatter + page model
# ─────────────────────────────────────────────────────────────────────────────

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")          # [text](target)
HEADER_RE = re.compile(r"^#{1,6}\s")
INLINE_CODE_RE = re.compile(r"`[^`]*`")                 # `inline code` — example links here don't count


def _links_in(line):
    """Yield link targets on a line, ignoring any inside inline-code spans."""
    scanned = INLINE_CODE_RE.sub(lambda m: " " * len(m.group()), line)
    return (m.group(1) for m in LINK_RE.finditer(scanned))


def parse_frontmatter(lines):
    """Return (fields dict, ok). Minimal YAML subset: scalars + inline/block lists."""
    if not lines or lines[0].rstrip() != "---":
        return {}, False
    fields, key = {}, None
    for i in range(1, len(lines)):
        line = lines[i].rstrip("\n")
        if line.rstrip() == "---":
            return fields, True
        m = re.match(r"^(\S[^:]*?):\s*(.*)$", line)
        if m:
            key, rawval = m.group(1).strip(), m.group(2).strip()
            fields[key] = _yaml_val(rawval)
        elif key and re.match(r"^\s*-\s+", line):          # block list continuation
            item = _strip_quotes(re.sub(r"^\s*-\s+", "", line).strip())
            prev = fields.get(key)
            fields[key] = (prev if isinstance(prev, list) else []) + [item]
    return fields, False   # no closing ---


def _yaml_val(v):
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        return [_strip_quotes(x.strip()) for x in inner.split(",") if x.strip()] if inner else []
    return _strip_quotes(v) if v else ""


def _strip_quotes(s):
    return s[1:-1] if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0] else s


class Page:
    def __init__(self, root, relpath):
        self.relpath = relpath
        self.abspath = os.path.join(root, relpath)
        with open(self.abspath, encoding="utf-8") as fh:
            self.lines = fh.readlines()
        self.fm, self.fm_ok = parse_frontmatter(self.lines)
        self.type = self.fm.get("type", "")
        self.stem = os.path.splitext(os.path.basename(relpath))[0]
        # first path segment under wiki/  (e.g. "concepts", "projects")
        parts = relpath.split(os.sep)
        self.segment = parts[1] if len(parts) > 2 and parts[0] == "wiki" else ""
        self.is_project_index = relpath.startswith(os.path.join("wiki", "projects")) and self.stem == "index"


# ─────────────────────────────────────────────────────────────────────────────
# Discovery
# ─────────────────────────────────────────────────────────────────────────────

def find_root(start):
    d = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(d, "conventions.toml")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def iter_wiki_pages(root):
    wiki_dir = os.path.join(root, "wiki")
    for dirpath, _dirs, files in os.walk(wiki_dir):
        for name in files:
            if name.endswith(".md"):
                yield os.path.relpath(os.path.join(dirpath, name), root)


def resolve_link(root, from_relpath, target):
    """Return repo-relative path a link resolves to, or None if external/anchor."""
    t = target.strip()
    if t.startswith(("http://", "https://", "mailto:", "#")):
        return None
    t = t.split("#", 1)[0].split("?", 1)[0].strip()
    if not t:
        return None
    base = os.path.dirname(os.path.join(root, from_relpath))
    abs_target = os.path.normpath(os.path.join(base, unquote(t)))
    return os.path.relpath(abs_target, root)


def link_severity(resolved):
    """A broken link's severity depends on where it points.

    Into wiki/ (.md) → ERROR: real knowledge-graph breakage.
    Into raw/         → INFO: a provenance pointer to immutable source material,
                        which is often gitignored/absent and not part of the graph.
    Anything else     → WARN: an asset/output link worth a look.
    """
    if resolved.startswith("wiki" + os.sep):
        return "error" if resolved.endswith(".md") else "warn"
    if resolved.startswith("raw" + os.sep):
        return "info"
    return "warn"


# ─────────────────────────────────────────────────────────────────────────────
# Lint
# ─────────────────────────────────────────────────────────────────────────────

def lint(root, cfg, type_filter=None):
    findings = []
    add = lambda *a, **k: findings.append(Finding(*a, **k))

    fm_required = cfg.get("frontmatter", {}).get("required", [])
    fm_by_type = cfg.get("frontmatter_by_type", {})
    type_enum = set(cfg.get("types", {}).get("enum", []))
    folder_map = cfg.get("folders", {})
    src_types = set(cfg.get("source_type", {}).get("enum", []))
    rel_cfg = cfg.get("related", {})
    rel_types, rel_min, rel_max = set(rel_cfg.get("types", [])), rel_cfg.get("min", 3), rel_cfg.get("max", 5)
    mk = cfg.get("markers", {})
    rel_header = mk.get("relevance_header")            # optional: only checked if declared
    rel_marker = mk.get("relevance_marker", "")
    overview_marker = mk.get("overview_marker")        # optional: only checked if declared
    soft, hard = cfg.get("size", {}).get("soft_cap", 450), cfg.get("size", {}).get("hard_cap", 900)
    stale = cfg.get("staleness", {})
    idx_cfg = cfg.get("index", {})
    tracked = set(idx_cfg.get("tracked_types", []))
    thin = cfg.get("thin_support", {})
    thin_types, thin_min = set(thin.get("types", [])), thin.get("min_source_links", 2)
    skip = cfg.get("skip", {})
    noninbound = set(skip.get("noninbound_files", []))
    no_linkcheck = set(skip.get("no_linkcheck_files", []))

    pages = [Page(root, rp) for rp in iter_wiki_pages(root)]
    if type_filter:
        pages = [p for p in pages if p.type == type_filter]
    by_relpath = {p.relpath: p for p in pages}
    wiki_paths = set(by_relpath)
    stem_to_paths = {}
    for p in pages:
        stem_to_paths.setdefault(p.stem, []).append(p.relpath)

    inbound = {p.relpath: set() for p in pages}          # target -> set of source relpaths

    # ── per-page checks ──────────────────────────────────────────────────────
    for p in pages:
        # frontmatter present & required fields
        if not p.fm_ok:
            add("error", "frontmatter-missing", p.relpath, "no valid YAML frontmatter block")
            continue
        for f in fm_required:
            if not p.fm.get(f):
                add("error", "frontmatter-field", p.relpath, f"missing required field `{f}`")
        # type enum + folder agreement
        if p.type and p.type not in type_enum:
            add("error", "type-unknown", p.relpath, f"type `{p.type}` not in the enum")
        expected = folder_map.get(p.segment)
        if expected and p.type and p.type != expected and not p.is_project_index:
            add("error", "type-folder", p.relpath, f"type `{p.type}` but folder implies `{expected}`")
        # per-type extra fields
        for f in fm_by_type.get(p.type, []):
            if not p.fm.get(f):
                add("warn", "frontmatter-type-field", p.relpath, f"{p.type} missing `{f}`")
        # source-type enum
        st = p.fm.get("source-type")
        if p.type == "source-note" and st and st not in src_types:
            add("warn", "source-type", p.relpath, f"source-type `{st}` not in the enum")
        # related field (concept/author)
        if p.type in rel_types:
            rel = p.fm.get("related")
            rel = rel if isinstance(rel, list) else ([rel] if rel else [])
            if not rel:
                add("info", "related-missing", p.relpath, "no `related:` field")
            elif not (rel_min <= len(rel) <= rel_max):
                add("info", "related-count", p.relpath, f"related has {len(rel)} entries (want {rel_min}-{rel_max})")
            for stem in rel:
                if stem and stem not in stem_to_paths:
                    add("warn", "related-broken", p.relpath, f"related `{stem}` resolves to no page")
                else:
                    for tgt in stem_to_paths.get(stem, []):
                        if tgt != p.relpath:
                            inbound[tgt].add(p.relpath)

        # links: broken-link check + inbound graph + thin-support tally
        src_link_count = 0
        in_fence = False
        for i, line in enumerate(p.lines, 1):
            stripped = line.lstrip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_fence = not in_fence
                continue
            if in_fence:                              # example links in code blocks don't count
                continue
            for target in _links_in(line):
                resolved = resolve_link(root, p.relpath, target)
                if resolved is None:
                    continue
                exists = os.path.exists(os.path.join(root, resolved))
                if not exists:
                    add(link_severity(resolved), "link-broken", p.relpath, f"link → `{resolved}` (missing)", line=i)
                elif resolved in wiki_paths and resolved != p.relpath:
                    inbound[resolved].add(p.relpath)
                if resolved.startswith(os.path.join("wiki", "source-notes")):
                    src_link_count += 1

            # epistemic-marker checks (header lines only) — only if the schema declares markers
            if HEADER_RE.match(line):
                if rel_header and rel_header in line and rel_marker not in line:
                    add("warn", "marker-relevance", p.relpath,
                        f"'{rel_header}' header missing {rel_marker}", line=i)
                if overview_marker and p.type == "synthesis" \
                        and re.match(r"^#{1,6}\s+Overview\b", line) and overview_marker not in line:
                    add("warn", "marker-overview", p.relpath,
                        f"synthesis Overview header missing {overview_marker}", line=i)

        # thin source support
        if p.type in thin_types and src_link_count < thin_min:
            add("info", "thin-support", p.relpath,
                f"{p.type} cites {src_link_count} source-note(s) (want ≥{thin_min})")

        # size caps
        n = len(p.lines)
        if n > hard:
            add("warn", "oversize", p.relpath, f"{n} lines (> hard cap {hard}) — consider splitting")
        elif n > soft:
            add("info", "oversize", p.relpath, f"{n} lines (> soft cap {soft})")

    # ── orphans + staleness (need the completed inbound graph) ────────────────
    today = date.today()
    for p in pages:
        if p.is_project_index:
            continue
        deg = len(inbound[p.relpath])
        if deg == 0:
            add("warn", "orphan", p.relpath, "no inbound links from any wiki page")
        # staleness: well-linked AND old, together
        if stale and deg >= stale.get("min_inbound_links", 5):
            upd = str(p.fm.get("updated", ""))
            m = re.match(r"(\d{4})-(\d{2})-(\d{2})", upd)
            if m:
                age = (today - date(int(m[1]), int(m[2]), int(m[3]))).days
                if age > stale.get("max_days_since_update", 180):
                    add("info", "stale", p.relpath, f"{age}d since update, {deg} inbound links")

    # ── index + meta-file checks (only meaningful once the wiki has content) ──
    if pages:
        # index drift (pages the index is meant to enumerate but doesn't)
        idx_file = idx_cfg.get("file", "index.md")
        idx_path = os.path.join(root, idx_file)
        if os.path.exists(idx_path):
            with open(idx_path, encoding="utf-8") as fh:
                idx_text = fh.read()
            indexed = set()
            for m in LINK_RE.finditer(idx_text):
                r = resolve_link(root, idx_file, m.group(1))
                if r:
                    indexed.add(r)
            for p in pages:
                if p.type in tracked and p.relpath not in indexed and not p.is_project_index:
                    add("info", "index-drift", p.relpath, "not linked from the index")

        # broken links inside root meta files (index.md, README.md, CLAUDE.md) — not log.md
        for meta in noninbound:
            if meta in no_linkcheck:
                continue
            mp = os.path.join(root, meta)
            if not os.path.exists(mp):
                continue
            in_fence = False
            with open(mp, encoding="utf-8") as fh:
                for i, line in enumerate(fh, 1):
                    stripped = line.lstrip()
                    if stripped.startswith("```") or stripped.startswith("~~~"):
                        in_fence = not in_fence
                        continue
                    if in_fence:                      # skip template examples in code blocks
                        continue
                    for target in _links_in(line):
                        r = resolve_link(root, meta, target)
                        if r and not os.path.exists(os.path.join(root, r)):
                            add(link_severity(r), "link-broken", meta, f"link → `{r}` (missing)", line=i)

    return findings, len(pages)


# ─────────────────────────────────────────────────────────────────────────────
# Reporting
# ─────────────────────────────────────────────────────────────────────────────

ICON = {"error": "✗", "warn": "!", "info": "·"}


def report(findings, npages, min_sev):
    floor = SEV[min_sev]
    shown = [f for f in findings if SEV[f.sev] >= floor]
    shown.sort(key=lambda f: (-SEV[f.sev], f.code, f.relpath, f.line))

    counts = {"error": 0, "warn": 0, "info": 0}
    for f in findings:
        counts[f.sev] += 1

    order = {"error": [], "warn": [], "info": []}
    for f in shown:
        order[f.sev].append(f)
    for sev in ("error", "warn", "info"):
        group = order[sev]
        if not group:
            continue
        print(f"\n{ICON[sev]} {sev.upper()} ({len(group)})")
        for f in group:
            print(f"  {f.loc()}  [{f.code}] {f.msg}")

    print(f"\n{'─'*60}")
    print(f"{npages} pages · {counts['error']} error · {counts['warn']} warn · {counts['info']} info")
    return counts["error"]


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(prog="wiki", description="Deterministic checks for the Research Wiki.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    lp = sub.add_parser("lint", help="check link integrity, orphans, index drift, frontmatter, markers")
    lp.add_argument("--root", help="wiki root (default: walk up for conventions.toml)")
    lp.add_argument("--min-severity", choices=["error", "warn", "info"], default="info")
    lp.add_argument("--type", help="restrict to one page type (e.g. concept, source-note)")
    args = ap.parse_args(argv)

    if args.cmd == "lint":
        root = os.path.abspath(args.root) if args.root else find_root(os.getcwd())
        cfg_path = os.path.join(root, "conventions.toml")
        if not os.path.exists(cfg_path):
            print(f"error: no conventions.toml at {root}", file=sys.stderr)
            return 2
        cfg = _load_toml(cfg_path)
        findings, npages = lint(root, cfg, type_filter=args.type)
        n_err = report(findings, npages, args.min_severity)
        return 1 if n_err else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())

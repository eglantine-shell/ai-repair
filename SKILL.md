---
name: ai-manuscript-repair
description: Repair accepted Chinese AI-generated manuscripts through understanding-based minimal language edits, with optional local consistency highlighting. Use when a manuscript cannot be rejected or broadly rewritten, and the editor needs an annotated PDF plus a page/original/corrected Markdown list. Do not use for general proofreading, AI detection, factual review, structural editing, or stylistic humanization.
---

# AI Manuscript Repair

## Purpose

Turn an accepted but difficult AI-generated manuscript into an editable work
object without rejecting it or rewriting it wholesale. Read enough surrounding
context to understand the intended proposition, then intervene only at the
smallest defensible span.

This is a distinct workflow, not a mode of general editorial review. Its
default pass targets a recurring AI-generation failure:

- locally fluent sentences whose semantic roles, relations, or wording fail
  under close reading;

An experimental optional pass can expose locally plausible but unstable names
for the same role, object, process, or concept. Do not enable it unless the
user asks for consistency highlighting or explicitly accepts that extra layer.

Read [references/method.md](references/method.md) when changing the review
criteria, output contract, or relationship between the two passes.

## Workflow

Run direct minimal repair by default: infer the intended meaning from the page
and adjacent context, then return only executable original/corrected pairs.

Local semantic consistency is opt-in. When requested, find likely same-referent
naming or role drift, but do not choose a preferred form or propose a
correction. Enable it with `--include-consistency`.

Do not set a target count or density cap. A clean page may have no edits; when
the optional pass is enabled, a genuinely unstable page may have many marks.

## Output contract

Create exactly these editor-facing deliverables from the same structured run:

- `minimal-edits.pdf`: preserve the source PDF page order and page count. Show
  direct edits as red underlines with the complete `修改为：……` stored in the
  annotation. When and only when consistency highlighting is enabled, show
  every occurrence of each candidate as a yellow highlight with no contents,
  title, popup note, canonical form, or proposed edit.
- `minimal-edits.md`: contain only `页码 | 原句 | 修改`.

Keep model reasons, prompt versions, hashes, failures, and provider metadata in
the run directory. Never expose those audit details in the PDF or Markdown.

## Judgment boundaries

Direct edits may repair wording, grammar, semantic-role mismatch, unclear
reference, false connective logic, mixed comparison levels, mechanical
repetition, empty emphasis, and other local language failures when the intended
meaning is sufficiently clear.

Do not add facts, strengthen claims, change the author's position, reorganize
paragraphs, invent a personal voice, or rewrite for elegance. If a problem
cannot be repaired locally without making an authorial decision, omit it from
the red layer.

When the optional consistency pass is enabled, yellow marks are deliberately
non-prescriptive. Include broad-to-specific role shifts when an editor may
reasonably need to decide whether the distinction is deliberate. Exclude normal
pronouns, defined short/full forms, and ordinary lexical variation that does
not destabilize a fixed role or concept.

## Run

The package is self-contained and does not import `editor-review`.

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/ai-manuscript-repair input.pdf --output-dir output
```

The command requires an authenticated Codex installation available to the
`openai-codex` SDK. Omit `--pages` for the complete book; use a value such as
`--pages 1-3,8` only for a bounded validation run.

Only add the experimental yellow consistency layer when it is explicitly
wanted:

```bash
.venv/bin/ai-manuscript-repair input.pdf --output-dir output --include-consistency
```

## Completion checks

Before delivery, require:

- every requested page has a completed direct-review record;
- every accepted red edit copies exact source text and is precisely placed;
- the output PDF page count equals the selected source scope;
- every red annotation contains the full correction and no audit reason;
- Markdown has only the three required columns;
- a rendered sample confirms red underlines are legible.

When consistency highlighting is enabled, additionally require every yellow
occurrence to copy exact source text and be precisely placed; every yellow
annotation must have no `/Contents` or `/T` entry, and the rendered sample must
confirm that the highlights are legible.

Never treat successful placement as proof that a language judgment is correct.
The professional editor retains every accept/reject and standardization
decision.

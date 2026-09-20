# Method and product boundary

## Problem setting

The manuscript has already been accepted. Rejecting it, asking for a complete
rewrite, or silently replacing it with a new article is outside the workflow.
The editor needs actionable entry points into a dense AI-generated draft.

The method therefore separates the scope of understanding from the scope of
intervention: contextual understanding may be broad, while every visible edit
must remain local and minimal.

## Default and optional intervention

### Direct repair

The red layer is prescriptive only when the intended proposition is recoverable
and the repair does not require new facts or a new authorial choice. It focuses
on semantic language failures that ordinary surface checking often misses:

- agent, action, and object mismatch;
- unclear reference or scope;
- collocation and modification failure;
- parallel items at incompatible levels;
- connective logic that does not express the actual relation;
- near-synonym stacking and abstract-noun accumulation;
- mechanical repetition or emphasis with no semantic function;
- claim strength distorted by generated wording.

### Consistency exposure (optional, experimental)

The yellow layer is disabled by default because its semantic clustering is less
stable than direct repair and can add substantial review noise. Enable it only
when the editor explicitly wants a consistency-attention layer.

When enabled, the yellow layer is descriptive. AI generation can produce individually
plausible labels without maintaining a stable discourse object. The model may
therefore identify a candidate cluster, but it must not decide which label is
canonical. Human judgment is required because a broad-to-specific role change
may be either an error or a deliberate distinction.

## De-AI significance

This workflow removes AI symptoms by repairing semantic instability, not by
simulating statistical markers of human prose. It does not vary sentence length
for its own sake, inject colloquialism, add personal anecdotes, or replace a
list of stereotypical AI words.

The method cannot solve content thinness, fabricated evidence, formulaic book
architecture, absent experience, or lack of authorial position. Those require
content development, structural editing, deletion, or rewriting.

It is not an AI detector. Human writing can contain the same defects, and a
clean result does not establish human authorship.

## Current implementation status

The independent package preserves the direct-repair behavior established in the
full-book experiment while removing dependencies on the general
`editor-review` package. Local consistency highlighting remains available as an
explicit opt-in experiment. The package currently targets horizontal,
text-layer Chinese PDFs. Scanned pages and complex vertical or multi-column
layouts require a separate text-recovery stage and are intentionally outside
version 0.2.

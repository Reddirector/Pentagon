---
name: document-writing
description: When to produce a file vs answer inline, which format fits which request, and how to build long documents iteratively. Use for reports, proposals, briefs, essays.
triggers:
  - write a report
  - document
  - draft
  - proposal
  - essay
  - brief
  - long-form
  - whitepaper
  - write it up
risk_category: write
---

# Writing documents well

## File or inline? Decide first, not last

- **Answer inline** when the content is under roughly 400 words or the user
  asked a question rather than commissioned a document. A one-paragraph
  reply wrapped in a file is friction, not deliverable.
- **Produce a file** when the user asks for a document, when the output will
  be reused (sent, submitted, versioned), or when structure matters more than
  the conversation: headings, tables, sections.
- If a file-creation capability is not available in this session, do not
  pretend one was created. Present the full document in the reply inside a
  single clearly-delimited block and say in one line that it could not be
  written to a file here.

## Format choice

| Request | Format |
|---|---|
| Report, brief, README, spec, anything with headings | Markdown |
| Something the user will open in Word or send to non-technical readers | `.docx` |
| Data that belongs in rows and columns | CSV, never a prose table |
| A slide-style summary | Markdown with `##` per slide — confirm before building anything fancier |

Ask before choosing an unusual format; default to Markdown when unsure.

## Structure long documents iteratively

1. **Outline first.** Confirm the sections (and length target) before
   drafting — or, if the user clearly wants speed, state the outline at the
   top of the first draft so it can be corrected cheaply.
2. **Draft section by section.** A 10-section document written in one pass
   drifts by section four: tone slips, claims repeat, an early decision gets
   contradicted later. Write sections deliberately and keep headings stable.
3. **Front-load the point.** The reader's first paragraph should carry the
   conclusion; background follows. Pentagon's house style is bottom-line up
   front.
4. **Cut before adding.** If a section adds no decision, fact or
   definition, delete it. Length is not value.
5. **Self-check at the end:** every section in the outline exists, numbers
   are consistent across sections, no placeholder text survives, and the
   title matches the content.

## Common pitfalls

- Don't bury requirements in prose when a numbered list is what the reader
  will act on.
- Don't invent figures. If a number is not given by the user or a cited
  source, write `[needs source]` and say so.
- Don't restate the prompt as the introduction; start with the document.

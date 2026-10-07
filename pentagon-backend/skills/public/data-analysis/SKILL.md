---
name: data-analysis
description: Inspect a dropped-in CSV before transforming it, state assumptions about ambiguous columns, and show trends as charts not raw tables. Use for questions about shared data files.
triggers:
  - csv
  - spreadsheet
  - dataset
  - analyze this data
  - plot
  - chart
  - statistics
  - trend over time
risk_category: read
requires_tools:
  - python_exec
  - read_document
---

# Analysing data the user shared

## Inspect before you transform

The first command is never the analysis — it is a look at what the data
actually is:

1. **Shape**: how many rows and columns? An empty or one-row file changes
   everything about what can be claimed.
2. **Columns**: names, inferred types, and units. `date` may be D/M or M/D;
   `revenue` may be dollars or cents; `id` may be numeric but is never a
   quantity.
3. **Quality**: missing values per column, duplicate rows, stray
   whitespace, mixed encodings, a header row buried at row 3.
4. **Range sanity**: dates that extend into the future, negative ages, a
   "category" column with 10,000 unique values (it is an id).

Only then compute anything.

## State assumptions out loud

Every ambiguous column gets an explicit assumption in the answer: "I read
`date` as day-first and `amount` as USD — say if either is wrong." Silent
assumptions are how an analysis looks right and is wrong. When an
assumption changes the result, show the result under both readings instead
of picking quietly.

## Trends are charts; exact values are small tables

- A trend over time, a distribution, or a comparison across categories
  calls for a **chart** — a wall of numbers in a table hides the shape it
  is trying to show.
- A short table is right for exact values a reader will reuse (totals,
  top-5 rows, summary statistics) — typically under ~10 rows.
- Never paste raw rows of a large dataset as the "answer". Aggregate
  first; show samples only when the sample is the point.
- Label axes and units in the chart description, and name the source file.

## Honesty rules

- Compute only from the file given — no plausible-sounding numbers from
  memory about "similar" data.
- Small samples get a caveat, not a conclusion ("3 rows — too few to call
  a trend").
- If the requested analysis needs a column that is not there, say which
  one and offer the nearest thing that is — do not substitute a lookalike
  silently.
- Keep the user's data in their own storage; do not paste large excerpts
  of it into unrelated places.

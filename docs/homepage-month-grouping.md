# Homepage Month Grouping Plan

## Goal

Starting in July 2026, visually group sessions by month on the home page while keeping the existing session URLs and sequential session numbers.

This is a display-only change for `templates/index.html`. It should not require moving content files.

## Current Structure

Session files stay flat under:

```text
content/fcz/
```

Examples:

```text
content/fcz/0024.md
content/fcz/0025.md
content/fcz/0026.md
```

Session URLs and numbering should remain sequential and stable:

```text
/fcz/0024/
/fcz/0025/
/fcz/0026/
```

## Desired Home Page Display

The home page should show the newest month first, then newest sessions first inside each month.

Example:

```text
Julho 2026
  Sessão #0026
  Sessão #0027

Junho 2026
  Sessão #0025
  Sessão #0024
  Sessão #0023
```

Exact ordering should match the current home page behavior: newest sessions first.

## Implementation Approach

Update `templates/index.html` only.

Use each page date to derive a month key, for example:

```tera
{{ page.date | date(format="%Y-%m") }}
```

Use each page date to render the visible month heading, for example:

```tera
{{ page.date | date(format="%B %Y", locale="pt_BR") }}
```

If locale formatting is not available or looks wrong in Zola/Tera, use a small explicit month-name mapping in the template instead.

Keep `content/fcz/_index.md` and session files unchanged unless the template needs a small extra field. Prefer deriving grouping from `date`.

## Expected Behavior

- Sessions from `2026-07-*` appear under `Julho 2026`.
- Sessions from `2026-06-*` appear under `Junho 2026`.
- Newest month appears first.
- Newest session appears first within each month.
- Session card contents remain the same.
- Existing session URLs do not change.

## Suggested Timing

Implement after session `0025` is wrapped or when creating/wrapping session `0026` on `2026-07-01`.

The feature becomes useful once July has at least one session and the home page would otherwise mix June and July in one flat list.

## Commands To Verify

After changing the template:

```sh
just build
```

Optionally run the local server for visual inspection:

```sh
just serve
```

Check the home page and verify:

- month headings appear once per month;
- session cards are still clickable;
- session order remains newest first;
- mobile layout still has clear spacing between month sections.

## Non-Goals

- Do not change session URLs.
- Do not change session numbering.
- Do not move session Markdown files into month directories.
- Do not change thumbnail paths as part of this homepage task.
- Do not add month metadata to existing session files unless deriving from `date` proves impractical.

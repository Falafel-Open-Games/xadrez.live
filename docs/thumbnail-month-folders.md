# Thumbnail Month Folders Plan

## Goal

Starting with session `0026` on `2026-07-01`, store new generated session thumbnails in monthly folders instead of continuing the flat `static/fcz/thumbnails/` directory.

This is only for new thumbnails. Do not move or rename existing June thumbnails.

## Current Structure

June thumbnails currently live directly under:

```text
static/fcz/thumbnails/
```

Examples:

```text
static/fcz/thumbnails/20260629-pre-thumb.jpg
static/fcz/thumbnails/20260629-post-thumb.jpg
static/fcz/thumbnails/20260630-pre-thumb.jpg
```

Keep these files where they are so existing `og_image` paths remain valid.

## New Structure From Session 0026

For session `0026` and later, write thumbnails into a `YYYY-MM` subdirectory:

```text
static/fcz/thumbnails/2026-07/20260701-pre-thumb.jpg
static/fcz/thumbnails/2026-07/20260701-post-thumb.jpg
```

For later months:

```text
static/fcz/thumbnails/2026-08/20260801-pre-thumb.jpg
static/fcz/thumbnails/2026-08/20260801-post-thumb.jpg
```

Keep the filename format unchanged:

```text
YYYYMMDD-pre-thumb.jpg
YYYYMMDD-post-thumb.jpg
```

The month folder is only for organization.

## Session Front Matter

For session `0026`, `og_image` should point to the new monthly path:

```toml
og_image = "/fcz/thumbnails/2026-07/20260701-pre-thumb.jpg"
```

After the post-live thumbnail is generated:

```toml
og_image = "/fcz/thumbnails/2026-07/20260701-post-thumb.jpg"
```

Old sessions can continue pointing to flat paths, for example:

```toml
og_image = "/fcz/thumbnails/20260629-post-thumb.jpg"
```

Mixed old and new paths are expected.

## Code Changes To Make

Update `scripts/prelive_thumbnail.py` so its default output path includes the month folder:

```text
static/fcz/thumbnails/YYYY-MM/YYYYMMDD-pre-thumb.jpg
```

The script already derives the output filename from the session `date`; use that same `date` to derive the `YYYY-MM` directory.

Keep explicit `-o/--output` behavior unchanged.

## Commands To Verify

After changing the script and creating session `0026`:

```sh
just pre-thumb 0026
just build
```

Expected generated file:

```text
static/fcz/thumbnails/2026-07/20260701-pre-thumb.jpg
```

Expected `content/fcz/0026.md` front matter:

```toml
og_image = "/fcz/thumbnails/2026-07/20260701-pre-thumb.jpg"
```

## Non-Goals

- Do not change session URLs.
- Do not change session numbering; continue with `0026`, `0027`, etc.
- Do not move existing June thumbnails.
- Do not migrate old `og_image` paths.
- Do not change homepage grouping as part of this thumbnail task.

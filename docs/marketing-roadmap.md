# xadrez.live Marketing Roadmap

This document tracks low-effort, high-leverage ways to grow the live stream audience and make the website more discoverable.

The working principle: the full livestream archive is valuable, but long VODs are weak discovery units. The archive should become raw material for smaller, searchable, shareable artifacts.

## Priorities

### 1. Turn Each Session Into Short Clips

Goal: create 2 to 4 small discovery assets from every stream.

Candidate clip types:

- One mistake lesson, usually from a capivarada or missed tactic.
- One puzzle or mate-pattern moment.
- One funny or useful chat interaction.
- One short session recap.

Why this matters:

- YouTube and Twitch are unlikely to recommend full beginner-study VODs to strangers without stronger engagement signals.
- Shorts/clips are easier for new viewers to sample.
- The site already has timelines, highlights, transcripts, and chapters, so the hard part is partly solved.

Low-effort next step:

- Manually publish 1 clip per session for 2 weeks.
- Track which clip type gets any impressions, views, comments, or site clicks.

Later automation:

- Use `data/fcz/highlights/*.json` to produce candidate clip ranges.
- Use `yt-dlp`/`ffmpeg` to export clips locally.
- Generate suggested titles/descriptions from the event metadata.

## 2. Improve YouTube Titles and Descriptions

Goal: make each VOD more searchable and more useful after the live ends.

Recommended title ingredients:

- Concrete chess term: `mate em 1`, `Epaulette Mate`, `Queen's Pawn Game`, `Chigorin Variation`.
- Human hook: `perdi no tempo`, `recusei captura`, `cavalo na beira`.
- Series identity: `xadrez depois dos 40`, when it fits naturally.

Description should include:

- One concise paragraph summarizing the session.
- Link to the xadrez.live session page.
- Chapters, already automated.
- Lichess game link.
- Practice set and puzzle links.
- Previous and next session links when available.

Low-effort next step:

- Extend the YouTube updater so it publishes more than chapters: summary, site link, game links, and practice links.

## 3. Make Topic Pages

Goal: give search engines and humans stable pages with clear intent, instead of only session logs.

Possible topic pages:

- `Mate em 1`
- `Capivaradas`
- `Checkmate Patterns`
- `Xadrez depois dos 40`
- `Queen's Pawn Game`
- `Chigorin Variation`

Why this matters:

- Session pages are chronological. Topic pages are intent-based.
- Searchers are more likely to search for a theme than for "Sessão #0053".
- Topic pages can aggregate sessions, timeline events, clips, and lessons.

Low-effort next step:

- Create one manually curated topic page for `Capivaradas`.
- Include the best 5 to 10 examples from existing sessions.

Later automation:

- Generate topic pages from openings, practice categories, timeline event kinds, and thumbnail notes.

## 4. Publish a Weekly Recap

Goal: create one shareable editorial artifact per week.

Suggested structure:

- Best lesson.
- Worst capivarada.
- Best puzzle or mate pattern.
- Chat moment.
- Next goal.

Why this matters:

- Weekly recaps are easier to share than individual session pages.
- They create a rhythm for non-live followers.
- They can link back to multiple VODs and pages.

Low-effort next step:

- Write one recap manually after the next 5 sessions.
- Keep it short enough to finish in 15 minutes.

Later automation:

- Draft recap from highlights, session descriptions, game notes, and chat replay.

## 5. Strengthen the Positioning

Goal: make the stream immediately understandable to a stranger.

Current strong identity:

- Practicing chess after 40.
- Real beginner/intermediate study.
- Public archive of mistakes, puzzles, chat, and progress.

Places where this should appear consistently:

- YouTube channel description.
- Twitch bio.
- Stream titles.
- Website homepage.
- VOD descriptions.
- Thumbnail language when appropriate.

Low-effort next step:

- Write a single positioning sentence and reuse it everywhere.

Example:

> Xadrez ao vivo depois dos 40: estudo real, puzzles, capivaradas e progresso público.

## 6. Keep Technical Discovery Healthy

Goal: remove avoidable friction for search engines and archives.

Already useful:

- Sitemap.
- IndexNow.
- Wayback submission.
- Session pages with structured data.
- YouTube chapters.

Low-effort next steps:

- Add `Sitemap: https://xadrez.live/sitemap.xml` to `robots.txt` if not already present.
- Keep Bing/Google warnings at zero when practical.
- Periodically submit updated URLs with IndexNow.
- Use Wayback submission after meaningful batches.

## Suggested Order

1. Improve YouTube descriptions.
2. Publish 1 clip per session manually for 2 weeks.
3. Create the first topic page: `Capivaradas`.
4. Write the first weekly recap.
5. Automate clip candidate exports.

This order favors things that can start generating signals quickly without requiring a large redesign or new platform strategy.

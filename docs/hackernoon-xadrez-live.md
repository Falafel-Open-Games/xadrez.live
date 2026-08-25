# How I Built an Open Source Publishing Workflow for Chess Streamers

Subtitle:

A static-site pipeline that turns chess livestreams into searchable pages with games, chat replay, transcripts, thumbnails, analytics, and SEO metadata.

TL;DR:

I built an open source workflow that turns chess livestreams into searchable static pages with game links, chat replay, transcripts, highlights, thumbnails, analytics, and SEO metadata. It started as a personal chess-learning archive and is evolving into tooling that could help other chess streamers make their live content less ephemeral.

Metadescription:

An open source workflow that turns chess livestreams into searchable static pages with games, chat, transcripts, thumbnails, analytics, and SEO.

Originally published in Portuguese on my personal blog: https://blog.fabricio.org/xadrez/

## Livestreams Are Bad Archives

Livestreams are great in the moment and surprisingly weak as archives.

After a stream ends, the recording usually becomes a long video with a title, a thumbnail, and maybe a description. That is fine for watching from the beginning, but bad for searching, revisiting, linking, and learning from specific moments.

I ran into this problem in a very personal way. Earlier this year, I got back into chess after years of treating it as a casual family game. I started practicing every day, opened accounts on online chess sites, fell in love with Lichess, and eventually decided to livestream my progress as an amateur player learning seriously after 40.

At first, I only wanted a simple page to record my sessions. Then the page started growing because every stream left behind useful fragments: game links, puzzle attempts, chat comments, mistakes, ratings, timestamps, and things I said out loud but would never find again inside a long video.

Chess streams make this problem more interesting because they already contain structured data: games, PGNs, moves, clocks, openings, engine evaluations, chat messages, and spoken commentary. The information is there, but most of it is trapped across platforms.

I built [xadrez.live](https://xadrez.live) to solve this for my own chess practice streams.

The project turns each livestream into a static session page with the video, games, chat replay, transcript, chapters, thumbnails, statistics, and metadata. The goal is not to replace YouTube, Twitch, Lichess, or Chess.com. It is to create a permanent layer around them that the streamer controls.

## The System

[xadrez.live](https://xadrez.live) is a static website built with [Zola](https://www.getzola.org/) and a collection of scripts around it.

The final public site does not need a backend database or application server. All the dynamic work happens before publishing: collecting game data, importing chat, generating transcripts, preparing thumbnails, writing metadata, building a search index, and producing the final static site.

Each stream gets a session page. A normal daily session, such as [session 0067](https://xadrez.live/fcz/0067/), can include:

- the embedded YouTube recording
- Lichess or Chess.com game links
- exported PGNs
- replayable mini boards
- chat replay data
- transcript blocks
- automatically generated chapters
- thumbnails and social preview images
- Open Graph and Twitter metadata
- structured statistics about the session

The important idea is that a stream becomes a document, not just a video.

## The Pipeline

The workflow starts during the stream.

A local userscript runs on Lichess, Chess.com, and Restream. It records puzzle URLs, game URLs, practice notes, timestamps, chat supporters, and other session data. At the end of the stream, it exports TOML and JSON files that feed the wrapup process.

After the stream, a terminal menu runs the daily wrapup. It imports userscript data, chat logs, ratings, Lichess analysis, editorial choices, thumbnails, YouTube metadata, validation results, and the final static site build.

This matters because a publishing system only works if it fits the routine. If wrapping a stream takes too much manual work, the archive will fall behind. The goal is to make the common path boring: run the menu, review the output, publish.

## Chess-Specific Data

The most useful part of the system is the chess-specific timeline.

For Lichess games, the scripts fetch PGNs and analysis data, then identify inaccuracies, mistakes, and blunders. Those events become timeline entries that can point back into the YouTube recording.

This creates chapters like:

```text
04:34 Game 1
05:54 Blunder
08:12 Blunder
21:42 Game 4
```

The implementation has to understand chess details, not just timestamps.

One example is Lichess arena berserk. In some arena games, a player can cut their own clock in half to get extra tournament points if they win. I ran into this during [session 0070](https://xadrez.live/fcz/0070/), a special Lichess Streamers Arena session. The PGN may include:

```text
[BlackBerserk "true"]
[TimeControl "300+0"]
```

If a script only reads `TimeControl`, it will assume both players started with five minutes. But the berserked player actually started with two and a half minutes. That can make the first move look like 150 seconds of thinking time.

I had to update the timeline calculation to treat berserk as a per-color clock setting. This is a small detail, but it is exactly the kind of detail that makes a generic video tool insufficient for chess streams.

## Search, Transcripts, and Chat

The site uses [Pagefind](https://pagefind.app/) to generate a static search index during the build.

Search works without a backend. It can cover descriptions, notes, chat messages, and transcript blocks. This makes old streams useful again. I can search for an opening, a repeated mistake, a phrase from the chat, or a position I remember discussing.

For transcripts, the pipeline supports multiple sources. It can import YouTube transcripts when they become available, or generate transcripts earlier using OpenAI audio transcription APIs or local Whisper tooling.

The transcript is not only for accessibility. It also turns spoken commentary into indexable text.

Chat replay is part of the archive too. The system imports and merges chat from YouTube, Twitch, and Restream. Chat often contains the real context of a stream: questions, jokes, move suggestions, corrections, and reactions to blunders.

## Publishing Tools

The workflow also prepares publishing metadata.

It can generate or update YouTube titles, description hooks, chapter blocks, session links, game links, previous and next session links, thumbnails, and live latency settings.

The thumbnail workflow creates pre-live and post-live thumbnails, social preview images, AI prompt drafts, bullet options, and YouTube thumbnail uploads. Thumbnail copy is treated separately from the session summary because a good thumbnail needs short, concrete hooks.

Analytics are handled with privacy-friendly tools such as Cloudflare Web Analytics, GoatCounter, and Ahrefs Web Analytics. The goal is not to track individual users. The goal is to understand discovery: which pages are found, which posts bring referrals, and whether the archive is actually helping people reach the project.

## Why Static Site Generation Works

A static site is a good fit for this problem.

The source data changes during the wrapup process, but the public pages do not need live server-side computation. Once a session is published, it is mostly immutable. Static HTML is fast, cheap, cacheable, and easy to host.

The build step becomes the integration layer. It collects data from chess platforms, video platforms, transcript tools, chat exports, and editorial scripts, then emits a site that search engines can crawl. The public site also has a [progress statistics page](https://xadrez.live/estatisticas/) and a short [about page](https://xadrez.live/sobre/) describing the project.

This also keeps ownership clear. The original video still lives on YouTube. The games still live on Lichess or Chess.com. But the archive page connects those pieces in one place.

## Open Source

The code is open source:

[https://github.com/Falafel-Open-Games/xadrez.live](https://github.com/Falafel-Open-Games/xadrez.live)

The project is licensed under AGPL v3.

Right now, xadrez.live is still shaped by my own daily use. I am the main user, tester, and developer. That is also why it has improved quickly: every script is driven by a real publishing workflow, not by imagined requirements.

My long-term hope is that parts of this system can help other chess streamers, especially Brazilian and Portuguese-speaking creators who want a more permanent, searchable home for their content.

Livestreams do not have to disappear into long, hard-to-search recordings. With the right pipeline, they can become structured archives.

For me, this started as a way to document a hobby. It became a practical reminder that small personal tools can grow into real infrastructure when they are used every day.

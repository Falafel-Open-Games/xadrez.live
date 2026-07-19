# External Stream Candidates

## Scope

This note tracks Brazilian/Portuguese chess streamers found from Lichess streamer pages that were considered for the external YouTube `/streams` aggregator.

The first implementation only tracks YouTube `/streams` pages. Twitch-only streamers are intentionally deferred.

## Included In The First YouTube Batch

These sources are configured in `data/external_stream_sources.toml`.

- `GM Krikor`
  - Source: `https://www.youtube.com/@GMKrikor/streams`
  - Reason: frequent GM online chess streams.
- `Everton Togni`
  - Source: `https://www.youtube.com/@evertontogni/streams`
  - Reason: large archive of Portuguese chess event/tournament streams.
- `CapaBlunder Chess`
  - Source: `https://www.youtube.com/@CapaBlunderChess/streams`
  - Reason: active community/tournament stream history.
- `Chess.com - Portugues`
  - Source: `https://www.youtube.com/@chesscomPT/streams`
  - Reason: official Portuguese tournament coverage.
- `Tr. Andre Basso`
  - Lichess: `https://lichess.org/streamer/basso01`
  - Source: `https://www.youtube.com/channel/UCHb90imHtSxw0EG4koem_Yw/streams`
  - Reason: YouTube streams include future scheduled chess lessons/lives.
- `Revista Xadrez Campos Gerais`
  - Lichess user: `https://lichess.org/streamer/egoncalves1313`
  - Source: `https://www.youtube.com/channel/UCLv7mOmR2XcRmji2c-WlzGg/streams`
  - Reason: recent tournament/event broadcast archive.
- `aerus15`
  - Source: `https://www.youtube.com/@aerus15/streams`
  - Reason: community stream source added from the xadrez.live chat.

## Deferred Candidates

### SergioGlorias

- Lichess: `https://lichess.org/streamer/SergioGlorias`
- Twitch: `https://www.twitch.tv/heyserginho`
- YouTube live URL from Lichess: `https://www.youtube.com/channel/UCpN2zCbAll35p45lr7kGVZg/live`
- YouTube streams page works, but the sampled latest stream was from `2023-05-26`.
- Decision: defer until there is newer YouTube stream activity, or until Twitch support exists.

### Deulefeu

- Lichess: `https://lichess.org/streamer/Deulefeu`
- Twitch: `https://www.twitch.tv/deulleffer`
- YouTube live URL from Lichess: `https://www.youtube.com/channel/UCcDqvGEOZt54qnN1K4986xg/live`
- YouTube streams page works, but the sampled latest stream was from `2025-08-20`.
- Decision: defer for now; monitor if recent YouTube chess streams resume.

### vvendell

- Lichess: `https://lichess.org/streamer/vvendell`
- Twitch: `https://www.twitch.tv/vvendellfb`
- YouTube live URL from Lichess: `https://www.youtube.com/channel/UCzt3T9isV6OAFOw2M58pqhg/live`
- YouTube streams page works, but the sampled latest stream was from `2024-11-02`.
- Decision: defer until there is current YouTube activity.

### ionsss

- Lichess: `https://lichess.org/streamer/ionsss`
- Twitch: `https://www.twitch.tv/leonardo_zara`
- No YouTube link was visible on the Lichess streamer page during the first pass.
- Decision: defer until Twitch support exists or a YouTube stream source is found.

### XadrezSemFoco

- Lichess: `https://lichess.org/streamer/XadrezSemFoco`
- Twitch: `https://www.twitch.tv/xadrezsemfoco`
- No YouTube link was visible on the Lichess streamer page during the first pass.
- Decision: defer until Twitch support exists or a YouTube stream source is found.

## Future Work

- Add Twitch support separately instead of forcing Twitch-only creators into the YouTube feed.
- Consider a `data/external_stream_candidates.toml` file if the list gets long enough to manage programmatically.
- Periodically re-check deferred YouTube channels for renewed activity.
- Keep the home page curated; do not show inactive sources just because their `/streams` URL works.

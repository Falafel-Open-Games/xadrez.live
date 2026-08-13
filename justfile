set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

default:
  @just --list

menu:
  @python3 scripts/daily_menu.py

serve: build-search
  zola serve

build: validate-session-games update-supporters update-site-stats update-lichess-rating-history export-session-pgns
  zola build
  python3 scripts/update_sitemap_lastmod.py

pagefind:
  npx -y pagefind@1.5.2

build-search: build pagefind

pre-wrap RECENT="2":
  @python3 scripts/import_youtube_chat_replays.py --cache-dir /tmp/xadrez-chat --latest {{RECENT}} --download
  @python3 scripts/import_twitch_chat_replays.py --cache-dir /tmp/xadrez-twitch-chat --playlist-end {{RECENT}}
  @python3 scripts/import_restream_chat_replays.py --cache-dir /tmp/xadrez-restream-chat --latest {{RECENT}} || echo "Restream chat unavailable; keeping direct-platform chat fallback"
  @python3 scripts/merge_chat_replays.py --latest {{RECENT}}
  @python3 scripts/import_youtube_transcripts.py --cache-dir /tmp/xadrez-transcripts --latest {{RECENT}}
  @python3 scripts/import_openai_transcripts.py --latest {{RECENT}} || echo "ATENCAO: transcricao GPT mini falhou ou ficou incompleta; rode just import-openai-transcript NNNN para retomar usando o cache de chunks"
  @python3 scripts/align_transcript_timestamps.py --latest {{RECENT}} --source-suffix openai-gpt-4o-mini-transcribe --output-suffix openai-gpt-4o-mini-transcribe.aligned
  @python3 scripts/align_transcript_timestamps.py --latest {{RECENT}} --source-suffix openai-gpt-4o-transcribe --output-suffix openai-gpt-4o-transcribe.aligned
  @python3 scripts/suggest_highlights.py --latest {{RECENT}}
  @python3 scripts/update_chat_supporters.py --latest {{RECENT}}
  @just build-search

wrap-session SESSION *ARGS:
  @python3 scripts/wrap_session.py {{SESSION}} {{ARGS}}

lint-actions:
  actionlint

check-editorial-spelling DICTIONARY="pt_BR":
  python3 scripts/check_editorial_spelling.py --dictionary {{DICTIONARY}}

review-editorial-spelling DICTIONARY="pt_BR":
  python3 scripts/review_editorial_spelling.py --dictionary {{DICTIONARY}}

apply-editorial-spelling *ARGS:
  python3 scripts/apply_editorial_spelling.py {{ARGS}}

update-external-streams:
  python3 scripts/update_external_streams.py

refresh-external-streams: update-external-streams build

wayback-submit *ARGS:
  @python3 scripts/submit_wayback.py {{ARGS}}

wayback-submit-all:
  @python3 scripts/submit_wayback.py --write

wayback-submit-test LIMIT="3" *ARGS:
  @python3 scripts/submit_wayback.py --limit {{LIMIT}} --write {{ARGS}}

update-youtube-chat-acks:
  @python3 scripts/update_youtube_chat_acks.py

update-chat-supporters EXTRA="":
  @python3 scripts/update_chat_supporters.py {{EXTRA}}

find-lichess-game-candidates SESSIONS="0001-0010" EXTRA="":
  @python3 scripts/find_lichess_game_candidates.py {{SESSIONS}} {{EXTRA}}

update-lichess-game-analysis EXTRA="":
  @python3 scripts/update_lichess_game_analysis.py {{EXTRA}}

export-session-pgns:
  @python3 scripts/export_session_pgns.py

missing-lichess-game-analysis:
  @python3 scripts/update_lichess_game_analysis.py --missing-only

backfill-lichess-pgns EXTRA="":
  @python3 scripts/update_lichess_game_analysis.py --missing-pgn-only {{EXTRA}}
  @just build

update-lichess-blunder-events EXTRA="":
  @python3 scripts/update_lichess_blunder_events.py {{EXTRA}}

calibrate-lichess-video-offset-only SESSION *ARGS:
  @python3 scripts/calibrate_lichess_video_offset.py {{SESSION}} {{ARGS}}

calibrate-lichess-video-offset SESSION *ARGS:
  @if python3 scripts/calibrate_lichess_video_offset.py {{SESSION}} --exit-code-on-skip 75 {{ARGS}}; then \
    python3 scripts/update_lichess_game_analysis.py {{SESSION}} --missing-only; \
    python3 scripts/update_lichess_blunder_events.py {{SESSION}}; \
    just build; \
    just youtube-chapters-write {{SESSION}}; \
  else \
    status=$?; \
    if [ "$status" -eq 75 ]; then exit 0; fi; \
    exit "$status"; \
  fi

calibrate-session-capivaradas SESSION *ARGS:
  @just calibrate-lichess-video-offset {{SESSION}} {{ARGS}}

update-session-capivaradas SESSION:
  @just update-session-capivaradas-data {{SESSION}}
  @just build

update-session-capivaradas-data SESSION:
  @python3 scripts/update_lichess_game_analysis.py {{SESSION}} --fetch-missing-only --missing-only
  @python3 scripts/update_lichess_blunder_events.py {{SESSION}}

update-youtube-video-metadata EXTRA="":
  @python3 scripts/update_youtube_video_metadata.py {{EXTRA}}

verify-session SESSION *ARGS:
  @python3 scripts/verify_session.py {{SESSION}} {{ARGS}}

youtube-chapters SESSION="" *ARGS:
  @python3 scripts/update_youtube_chapters.py {{SESSION}} {{ARGS}}

youtube-chapters-missing:
  @python3 scripts/update_youtube_chapters.py --missing-only

youtube-chapters-backfill:
  @python3 scripts/update_youtube_chapters.py --missing-only --write

youtube-descriptions-backfill RANGE:
  @python3 scripts/update_youtube_chapters.py {{RANGE}} --write

youtube-chapters-write SESSION="":
  @python3 scripts/update_youtube_chapters.py {{SESSION}} --write

youtube-chapters-write-confirm SESSION="":
  @python3 scripts/update_youtube_chapters.py {{SESSION}} --write --confirm

youtube-chapters-authorize:
  @python3 scripts/update_youtube_chapters.py --authorize --write-env

youtube-thumbnail SESSION:
  @python3 scripts/update_youtube_thumbnail.py {{SESSION}} --write

youtube-thumbnail-check SESSION:
  @python3 scripts/update_youtube_thumbnail.py {{SESSION}}

youtube-title-options SESSION:
  @python3 scripts/youtube_title_options.py {{SESSION}}

youtube-title-choose SESSION:
  @python3 scripts/youtube_title_options.py {{SESSION}} --choose --write

youtube-title-write SESSION TITLE:
  @python3 scripts/youtube_title_options.py {{SESSION}} --title "{{TITLE}}" --write

youtube-hook-options SESSION:
  @python3 scripts/youtube_title_options.py {{SESSION}} --kind hook

youtube-hook-choose SESSION:
  @python3 scripts/youtube_title_options.py {{SESSION}} --kind hook --choose --write

page-summary-options SESSION:
  @python3 scripts/session_summary_options.py {{SESSION}}

page-summary-choose SESSION:
  @python3 scripts/session_summary_options.py {{SESSION}} --choose --write

thumbnail-bullets SESSION:
  @python3 scripts/thumbnail_bullet_options.py {{SESSION}}

thumbnail-bullets-choose SESSION:
  @python3 scripts/thumbnail_bullet_options.py {{SESSION}} --choose --write --generate

youtube-finish-session SESSION:
  @just youtube-finish-session-no-build {{SESSION}}
  @just build

youtube-finish-session-no-build SESSION:
  @just verify-session {{SESSION}}
  @just page-summary-choose {{SESSION}}
  @just youtube-title-choose {{SESSION}}
  @just youtube-hook-choose {{SESSION}}
  @just thumbnail-bullets-choose {{SESSION}}
  @just youtube-chapters-write-confirm {{SESSION}}
  @just youtube-thumbnail {{SESSION}}
  @just verify-session {{SESSION}} --require-published-thumbnail

youtube-finish-session-skip-title SESSION:
  @just youtube-finish-session-skip-title-no-build {{SESSION}}
  @just build

youtube-finish-session-skip-title-no-build SESSION:
  @just verify-session {{SESSION}}
  @just page-summary-choose {{SESSION}}
  @just youtube-hook-choose {{SESSION}}
  @just thumbnail-bullets-choose {{SESSION}}
  @just youtube-chapters-write-confirm {{SESSION}}
  @just youtube-thumbnail {{SESSION}}
  @just verify-session {{SESSION}} --require-published-thumbnail

import-youtube-chat-replays CACHE_DIR="/tmp/xadrez-chat" EXTRA="":
  @python3 scripts/import_youtube_chat_replays.py --cache-dir {{CACHE_DIR}} {{EXTRA}}

merge-chat-replays EXTRA="":
  @python3 scripts/merge_chat_replays.py {{EXTRA}}

suggest-highlights SESSION EXTRA="":
  @python3 scripts/suggest_highlights.py {{SESSION}} {{EXTRA}}

suggest-highlights-all EXTRA="":
  @python3 scripts/suggest_highlights.py --all {{EXTRA}}

import-youtube-transcripts CACHE_DIR="/tmp/xadrez-transcripts" EXTRA="":
  @python3 scripts/import_youtube_transcripts.py --cache-dir {{CACHE_DIR}} {{EXTRA}}

import-whisper-transcript SESSION EXTRA="":
  @python3 scripts/import_whisper_transcripts.py --source-id faster-whisper --output-suffix faster-whisper --whisper-cache-dir /tmp/xadrez-faster-whisper-cache --whisper-cmd "whisper-ctranslate2 --model turbo --compute_type int8 --batched True --batch_size 8" {{EXTRA}} {{SESSION}}

import-faster-whisper-transcript SESSION EXTRA="":
  @python3 scripts/import_whisper_transcripts.py --source-id faster-whisper --output-suffix faster-whisper --whisper-cache-dir /tmp/xadrez-faster-whisper-cache --whisper-cmd "whisper-ctranslate2 --model turbo --compute_type int8 --batched True --batch_size 8" {{EXTRA}} {{SESSION}}

import-timed-transcript SESSION EXTRA="":
  @python3 scripts/align_transcript_timestamps.py --source-suffix openai-gpt-4o-mini-transcribe --output-suffix openai-gpt-4o-mini-transcribe.aligned {{SESSION}}
  @test ! -f data/fcz/transcripts/{{SESSION}}.openai-gpt-4o-transcribe.json || python3 scripts/align_transcript_timestamps.py --source-suffix openai-gpt-4o-transcribe --output-suffix openai-gpt-4o-transcribe.aligned {{SESSION}}
  @python3 scripts/suggest_highlights.py {{SESSION}}
  @just build

realign-highlights SESSION:
  @just import-timed-transcript {{SESSION}}

align-gpt4o-transcript SESSION:
  @python3 scripts/align_transcript_timestamps.py --source-suffix openai-gpt-4o-transcribe --output-suffix openai-gpt-4o-transcribe.aligned {{SESSION}}

import-missing-faster-whisper-transcripts EXTRA="":
  @sessions="$(python3 scripts/missing_faster_whisper_sessions.py)"; \
    if [ -z "$sessions" ]; then \
      echo "No missing faster-whisper transcripts for ended sessions."; \
      exit 0; \
    fi; \
    echo "Importing faster-whisper transcripts for: $sessions"; \
    OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 NUMEXPR_NUM_THREADS=2 \
    nice -n 10 ionice -c2 -n7 \
    python3 scripts/import_whisper_transcripts.py \
      --source-id faster-whisper \
      --output-suffix faster-whisper \
      --whisper-cache-dir /tmp/xadrez-faster-whisper-cache \
      --whisper-cmd "whisper-ctranslate2 --model turbo --threads 2 --compute_type int8 --batched True --batch_size 4" \
      --progress-interval-seconds 600 \
      --heartbeat-interval-seconds 300 \
      {{EXTRA}} \
      $sessions

import-slow-whisper-transcript SESSION EXTRA="":
  @OPENBLAS_NUM_THREADS=4 OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 NUMEXPR_NUM_THREADS=4 python3 scripts/import_whisper_transcripts.py {{EXTRA}} {{SESSION}}

import-openai-transcript SESSION EXTRA="":
  @python3 scripts/import_openai_transcripts.py {{EXTRA}} {{SESSION}}
  @python3 scripts/suggest_highlights.py {{SESSION}}
  @just build

draft-highlights SESSION:
  @python3 scripts/import_openai_transcripts.py {{SESSION}}
  @python3 scripts/suggest_highlights.py {{SESSION}}
  @just build

refresh-openai-transcripts RECENT="1" EXTRA="":
  @python3 scripts/import_openai_transcripts.py --latest {{RECENT}} {{EXTRA}}

align-transcript-timestamps SESSION EXTRA="":
  @python3 scripts/align_transcript_timestamps.py {{EXTRA}} {{SESSION}}

refine-highlights SESSION:
  @python3 scripts/align_transcript_timestamps.py --source-suffix openai-gpt-4o-mini-transcribe --output-suffix openai-gpt-4o-mini-transcribe.aligned {{SESSION}}
  @python3 scripts/suggest_highlights.py {{SESSION}}
  @just build

backfill-aligned-openai-transcripts EXTRA="":
  @python3 scripts/align_transcript_timestamps.py --all-existing --source-suffix openai-gpt-4o-mini-transcribe --output-suffix openai-gpt-4o-mini-transcribe.aligned {{EXTRA}}
  @python3 scripts/align_transcript_timestamps.py --all-existing --source-suffix openai-gpt-4o-transcribe --output-suffix openai-gpt-4o-transcribe.aligned {{EXTRA}}

import-restream-chat-replays CACHE_DIR="/tmp/xadrez-restream-chat" EXTRA="":
  @python3 scripts/import_restream_chat_replays.py --cache-dir {{CACHE_DIR}} {{EXTRA}}

import-restream-chat-html SESSION INPUT:
  @python3 scripts/import_restream_chat_html.py {{SESSION}} {{INPUT}}

import-twitch-chat-replays CACHE_DIR="/tmp/xadrez-twitch-chat" EXTRA="":
  @python3 scripts/import_twitch_chat_replays.py --cache-dir {{CACHE_DIR}} {{EXTRA}}

restream-oauth REDIRECT_URI="http://127.0.0.1:8765/restream/oauth/callback":
  @python3 scripts/restream_oauth.py authorize --redirect-uri {{REDIRECT_URI}} --write-env

restream-refresh-token:
  @python3 scripts/restream_oauth.py refresh --write-env

refresh-youtube-replay-data RECENT="5":
  @python3 scripts/import_youtube_chat_replays.py --cache-dir /tmp/xadrez-chat --latest {{RECENT}} --download
  @python3 scripts/merge_chat_replays.py --latest {{RECENT}}
  @python3 scripts/import_youtube_transcripts.py --cache-dir /tmp/xadrez-transcripts --latest {{RECENT}}

refresh-replay-data RECENT="5":
  @python3 scripts/import_youtube_chat_replays.py --cache-dir /tmp/xadrez-chat --latest {{RECENT}} --download
  @python3 scripts/import_twitch_chat_replays.py --cache-dir /tmp/xadrez-twitch-chat --playlist-end {{RECENT}}
  @python3 scripts/import_restream_chat_replays.py --cache-dir /tmp/xadrez-restream-chat --latest {{RECENT}} || echo "Restream chat unavailable; keeping YouTube-only chat fallback"
  @python3 scripts/merge_chat_replays.py --latest {{RECENT}}
  @python3 scripts/import_youtube_transcripts.py --cache-dir /tmp/xadrez-transcripts --latest {{RECENT}}
  @python3 scripts/import_openai_transcripts.py --latest 1 || echo "OpenAI transcript unavailable; keeping existing transcript fallback"

update-supporters:
  @python3 scripts/update_supporters.py

update-site-stats:
  @python3 scripts/update_site_stats.py

update-lichess-rating-history:
  @python3 scripts/update_lichess_rating_history.py

validate-session-games:
  @python3 scripts/normalize_lichess_game_urls.py

normalize-session-games:
  @python3 scripts/normalize_lichess_game_urls.py --write

discover-lichess-youtube-streamers LANGUAGE="all" PAGES="80":
  @python3 scripts/discover_lichess_streamers.py --service youtube --language {{LANGUAGE}} --limit-pages {{PAGES}} --latest-video

thumbnail-prompt SESSION KIND="post":
  @python3 scripts/thumbnail_prompt.py {{SESSION}} {{KIND}}

pre-thumb-local SESSION TIME="":
  @python3 scripts/prelive_thumbnail.py {{SESSION}} {{TIME}}

pre-thumb SESSION TIME="":
  @just pre-thumb-local {{SESSION}} {{TIME}}
  @just youtube-thumbnail {{SESSION}}

pre-thumb-youtube SESSION TIME="":
  @just pre-thumb {{SESSION}} {{TIME}}

post-thumb SESSION:
  @python3 scripts/postlive_thumbnail.py {{SESSION}}

thumbnail-optimize INPUT OUTPUT:
  @magick "{{INPUT}}" -strip -resize 1200x675 -quality 85 "{{OUTPUT}}"

schedule-next-session *ARGS:
  @python3 scripts/schedule_next_session.py {{ARGS}}

init-session number:
  @python3 scripts/schedule_next_session.py {{number}} --date "$(date +%F)" --time 11:00 --youtube https://youtube.com/live/REPLACE_WITH_YOUTUBE_VIDEO_ID --no-prompt

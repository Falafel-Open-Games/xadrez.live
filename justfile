set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

default:
  @just --list

serve:
  zola serve

build: update-supporters
  zola build

lint-actions:
  actionlint

update-external-streams:
  python3 scripts/update_external_streams.py

refresh-external-streams: update-external-streams build

update-youtube-chat-acks:
  @python3 scripts/update_youtube_chat_acks.py

import-youtube-chat-replays CACHE_DIR="/tmp/xadrez-chat" EXTRA="":
  @python3 scripts/import_youtube_chat_replays.py --cache-dir {{CACHE_DIR}} {{EXTRA}}

import-youtube-transcripts CACHE_DIR="/tmp/xadrez-transcripts" EXTRA="":
  @python3 scripts/import_youtube_transcripts.py --cache-dir {{CACHE_DIR}} {{EXTRA}}

import-whisper-transcript SESSION EXTRA="":
  @OPENBLAS_NUM_THREADS=4 OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 NUMEXPR_NUM_THREADS=4 python3 scripts/import_whisper_transcripts.py {{EXTRA}} {{SESSION}}

import-faster-whisper-transcript SESSION EXTRA="":
  @python3 scripts/import_whisper_transcripts.py --source-id faster-whisper --output-suffix faster-whisper --whisper-cache-dir /tmp/xadrez-faster-whisper-cache --whisper-cmd "whisper-ctranslate2 --model turbo --threads 4 --compute_type int8 --batched True --batch_size 8" {{EXTRA}} {{SESSION}}

import-openai-transcript SESSION EXTRA="":
  @python3 scripts/import_openai_transcripts.py {{EXTRA}} {{SESSION}}

refresh-openai-transcripts RECENT="1" EXTRA="":
  @python3 scripts/import_openai_transcripts.py --latest {{RECENT}} {{EXTRA}}

import-restream-chat-replays CACHE_DIR="/tmp/xadrez-restream-chat" EXTRA="":
  @python3 scripts/import_restream_chat_replays.py --cache-dir {{CACHE_DIR}} {{EXTRA}}

import-twitch-chat-replays CACHE_DIR="/tmp/xadrez-twitch-chat" EXTRA="":
  @python3 scripts/import_twitch_chat_replays.py --cache-dir {{CACHE_DIR}} {{EXTRA}}

restream-oauth REDIRECT_URI="http://127.0.0.1:8765/restream/oauth/callback":
  @python3 scripts/restream_oauth.py authorize --redirect-uri {{REDIRECT_URI}} --write-env

restream-refresh-token:
  @python3 scripts/restream_oauth.py refresh --write-env

refresh-youtube-replay-data RECENT="5":
  @python3 scripts/import_youtube_chat_replays.py --cache-dir /tmp/xadrez-chat --latest {{RECENT}} --download
  @python3 scripts/import_youtube_transcripts.py --cache-dir /tmp/xadrez-transcripts --latest {{RECENT}}

refresh-replay-data RECENT="5":
  @python3 scripts/import_youtube_chat_replays.py --cache-dir /tmp/xadrez-chat --latest {{RECENT}} --download
  @python3 scripts/import_twitch_chat_replays.py --cache-dir /tmp/xadrez-twitch-chat --playlist-end {{RECENT}}
  @python3 scripts/import_restream_chat_replays.py --cache-dir /tmp/xadrez-restream-chat --latest {{RECENT}} || echo "Restream chat unavailable; keeping YouTube-only chat fallback"
  @python3 scripts/import_youtube_transcripts.py --cache-dir /tmp/xadrez-transcripts --latest {{RECENT}}
  @python3 scripts/import_openai_transcripts.py --latest 1 || echo "OpenAI transcript unavailable; keeping existing transcript fallback"
  @python3 scripts/import_whisper_transcripts.py --latest 1 --source-id faster-whisper --output-suffix faster-whisper --whisper-cache-dir /tmp/xadrez-faster-whisper-cache --whisper-cmd "whisper-ctranslate2 --model turbo --threads 4 --compute_type int8 --batched True --batch_size 8" || echo "Faster Whisper CLI transcript unavailable; keeping existing transcript fallback"

update-supporters:
  @python3 scripts/update_supporters.py

discover-lichess-youtube-streamers LANGUAGE="all" PAGES="80":
  @python3 scripts/discover_lichess_streamers.py --service youtube --language {{LANGUAGE}} --limit-pages {{PAGES}} --latest-video

thumbnail-prompt SESSION KIND="post":
  @python3 scripts/thumbnail_prompt.py {{SESSION}} {{KIND}}

pre-thumb SESSION TIME="":
  @python3 scripts/prelive_thumbnail.py {{SESSION}} {{TIME}}

post-thumb SESSION:
  @python3 scripts/postlive_thumbnail.py {{SESSION}}

thumbnail-optimize INPUT OUTPUT:
  @magick "{{INPUT}}" -strip -resize 1200x675 -quality 85 "{{OUTPUT}}"

init-session number:
  @file="content/fcz/{{number}}.md"; today="$(date +%F)"; \
    test ! -e "$file" || { echo "$file already exists"; exit 1; }; \
    cp content/fcz/_session-template.md "$file"; \
    sed -i \
      -e "s/Sessão #00XX/Sessão #{{number}}/g" \
      -e "s/session_number = \"00XX\"/session_number = \"{{number}}\"/g" \
      -e "s/date = 2000-01-01/date = ${today}/g" \
      -e "s/draft = true/draft = false/g" \
      "$file"; \
    echo "Created $file"

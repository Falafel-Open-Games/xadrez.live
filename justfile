set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

default:
  @just --list

serve:
  zola serve

build:
  zola build

lint-actions:
  actionlint

update-external-streams:
  python3 scripts/update_external_streams.py

refresh-external-streams: update-external-streams build

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

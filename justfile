set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

default:
  @just --list

serve:
  zola serve

build:
  zola build

thumbnail-prompt SESSION KIND="post":
  @python3 scripts/thumbnail_prompt.py {{SESSION}} {{KIND}}

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

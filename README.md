# xadrez.live

Site estático mínimo em Zola para o diário pessoal de lives de xadrez em [xadrez.live](https://xadrez.live/).

## Instalar Zola

No macOS:

```sh
brew install zola
```

No Arch Linux:

```sh
sudo pacman -S zola
```

Outras opções estão na documentação oficial do Zola: <https://www.getzola.org/documentation/getting-started/installation/>

## Rodar localmente

Para procurar erros de ortografia nos textos editoriais, instale o dicionário brasileiro do Hunspell e rode:

```bash
sudo pacman -S hunspell-en_us
yay -S hunspell-pt-br
just check-editorial-spelling
```

O comando não altera arquivos. Por padrão, agrupa ocorrências por palavra e lista alguns locais de exemplo; use `python3 scripts/check_editorial_spelling.py --all` para ver cada ocorrência. Nomes e termos específicos ficam em `data/editorial_spelling_ignore.txt`.

Palavras aceitas exatamente pelo dicionário `en_US`, como `accepted` e `analytics`, são excluídas das suspeitas em português. Use `--no-english-filter` para desativar esse filtro.

Para revisar as suspeitas interativamente, use `just review-editorial-spelling`. A ferramenta percorre primeiro as correções de acento e depois as demais; `s` ignora, `a` aprova a primeira sugestão, `aN` aprova a sugestão numerada `N`, `c` permite informar uma substituição customizada, `d` adiciona a palavra ao dicionário personalizado e `q` encerra. Aprovações ficam em `data/editorial_spelling_approvals.json`; o conteúdo original não é alterado.

Para testar as aprovações sem alterar arquivos, rode `just apply-editorial-spelling`. O comando faz dry-run por padrão; depois de revisar a lista, use `just apply-editorial-spelling --write` para gravar as substituições.

```sh
zola serve
```

Depois abra o endereço mostrado no terminal. A sessão atual fica em:

```text
http://127.0.0.1:1111/fcz/0010/
```

Se tiver `just` instalado:

```sh
just serve
```

## Editar o video da sessão 0010

Abra `content/fcz/0010.md` e troque:

```toml
youtube_video_id = "REPLACE_WITH_YOUTUBE_VIDEO_ID"
```

pelo ID real do video ou live do YouTube.

Para publicar antes da live começar, deixe o badge como agendado:

```toml
status = "marcada para hoje às 11:00"
status_tone = "scheduled"
```

Quando a live estiver começando, se quiser atualizar o site:

```toml
status = "ao vivo agora"
status_tone = "live"
```

Depois da live:

```toml
status = "live encerrada"
status_tone = "ended"
```

Também é possível registrar o que aconteceu na sessão com campos opcionais:

```toml
lichess_game_url = "https://lichess.org/vjMTBtavUuFz"
puzzle_of_the_day_url = "https://lichess.org/training/vdpRb"
duration = "45 min"
rapid = "1 partida"
puzzles = "12"
streak = "5"
streak_goal = "5"
streak_best_sequence = ["Ehn4s", "PaCcT", "V333B", "ggje9", "yCuNx"]
result = "0-1"
opening = "Defesa Siciliana"
opening_url = "https://lichess.org/opening/Sicilian_Defense"
color = "brancas"
```

Campos vazios não aparecem na página.

### Calibrar timestamps do replay

Para obter uma sugestão de offset a partir do momento em que as brancas finalizam o segundo movimento na primeira partida:

```sh
just calibrate-lichess-video-offset 0052
```

O comando busca o PGN, informa qual relógio branco deve aparecer no quadro, pede o timestamp observado no vídeo, mostra a diferença em relação à âncora bruta calculada pelo Lichess e não altera nenhum arquivo. Revise a sugestão antes de registrá-la como `lichess_video_offset_seconds` no front matter.

### Capítulos do YouTube

A timeline pode gerar uma prévia dos capítulos sem alterar o YouTube:

```sh
just youtube-chapters
just youtube-chapters 0052
```

Para publicar capítulos, configure `YOUTUBE_CLIENT_ID` e `YOUTUBE_CLIENT_SECRET` de um cliente OAuth do Google Cloud, autorize uma vez e salve o refresh token:

```sh
just youtube-chapters-authorize
just youtube-chapters-write
```

O comando de escrita preserva a descrição existente e substitui somente o bloco entre `[xadrez.live chapters:start]` e `[xadrez.live chapters:end]`. Sem `--write`, ele sempre faz apenas dry-run.

Use o corpo Markdown do arquivo para a agenda e notas livres da sessão:

```md
## Agenda

- Puzzle of the Day: **fail**
- Puzzle streak 5: **ok (8)**
- Rapid 10min vs human: **win**

## Perfil ao final da sessão

- Rapid rating:
- Puzzles:
- Puzzle streak:
```

## Criar a próxima sessão

Use o template em branco:

```sh
just init-session 0011
```

Ou copie manualmente:

```sh
cp content/fcz/_session-template.md content/fcz/0011.md
```

Depois edite `content/fcz/0011.md`, atualizando `title`, `session_number`, `youtube_video_id`, `date`, `status`, `status_tone`, `tagline` e `description`. Se copiar manualmente, troque também `draft = true` para `draft = false`.

### Proveniência editorial

Blocos editoriais produzidos durante o wrapup podem registrar sua proveniência no front matter, em `[extra.editorial]` e `[[extra.editorial.provenance]]`. Cada entrada deve indicar o `field` afetado (`description`, `summary_title`, `agenda`, `notes` ou `thumbnail_notes`), as `sources` usadas, e os flags `ai_assisted` e `human_reviewed`.

Notas no campo `note` de uma partida devem registrar `note_author`, `note_origin` e `note_ai_assisted`. Quando forem escritas pelo streamer durante a análise ao vivo, use `note_origin = "human_live_analysis"` e `note_ai_assisted = false`; elas são fontes primárias humanas, mesmo quando depois alimentam uma síntese editorial assistida por IA.

Use fontes estáveis e separadas: `user_notes`, `game_notes`, `lichess_game_note`, `chat_context`, `chat_replay`, `transcript`, `lichess_analysis` e `lichess_practice`. Para sessões antigas cuja origem precisou ser reconstruída, use `provenance_status = "reconstructed"`; para sessões novas, prefira `verified` quando a trilha foi registrada durante o wrapup.

O campo opcional `time` aparece ao lado da data na home:

```toml
time = "11:00"
```

## Thumbnails

Para gerar um prompt de preenchimento da thumbnail antes da live:

```sh
just thumbnail-prompt 0010 pre
```

Para gerar um prompt de preenchimento da thumbnail depois da sessão:

```sh
just thumbnail-prompt 0010 post
```

O comando lê `content/fcz/0010.md`, extrai os dados do front matter e imprime um prompt limpo para copiar e colar no ChatGPT Web. Faça upload manual da imagem de template correspondente, cole o prompt gerado e use a imagem final como thumbnail da sessão.

Antes de usar a imagem gerada como preview social/Twitter da sessão, gere uma versão leve para servir pelo site:

```sh
just thumbnail-optimize static/fcz/thumbnails/20260616-pre-thumb.png static/fcz/thumbnails/20260616-pre-thumb.jpg
```

Referencie a imagem otimizada no front matter:

```toml
og_image = "/fcz/thumbnails/20260616-pre-thumb.jpg"
```

O arquivo em `og_image` é usado só nas tags Open Graph/Twitter; ele não aparece no corpo da página.

## Coletar dados da live no Lichess

Durante a live, use o userscript local em `tools/userscripts/xadrez-live-lichess-collector.user.js` para reduzir copia/cola de URLs do Lichess, do Chess.com e do chat do Restream. Ele adiciona um painel flutuante em `lichess.org`, `chess.com` e `chat.restream.io` com botões para:

- adicionar a URL do puzzle atual
- registrar a URL do Puzzle do Dia separadamente
- fechar uma tentativa de streak
- adicionar a URL da partida atual no Lichess ou no Chess.com
- registrar notas gerais e notas específicas da prática de puzzles antes da rapid, separadas no TOML do wrapup
- extrair usernames do chat do Restream e incluir os apoiadores no mesmo TOML da sessão
- copiar um JSON do replay de chat carregado no Restream para importar mais cedo no site
- copiar um bloco TOML pronto para colar no front matter da sessão

Os dados ficam só no storage local do gerenciador de userscripts, compartilhado entre os domínios onde o script roda. Não há servidor, login externo nem envio de dados para fora.

### Gerenciador de userscripts

Em 2026, o ecossistema está diferente da época clássica do Greasemonkey:

- Greasemonkey continua relevante principalmente no Firefox.
- Tampermonkey é o mais popular e funciona em vários navegadores, mas é proprietário/donationware.
- Violentmonkey é open source e sem anúncios, mas o próprio projeto informa que não é mais suportado no Chrome por causa da arquitetura Manifest V2.
- ScriptCat é open source, GPLv3, compatível com scripts no estilo Tampermonkey e disponível para Chrome/Chromium.

Para Chromium, este projeto recomenda **ScriptCat**: ele é open source e continua disponível na Chrome Web Store.

### Instalar no Chromium com ScriptCat

1. Instale o ScriptCat pela Chrome Web Store: <https://chromewebstore.google.com/>
2. Abra o dashboard do ScriptCat.
3. Crie um novo script.
4. Copie o conteúdo de `tools/userscripts/xadrez-live-lichess-collector.user.js`.
5. Cole no editor do ScriptCat e salve.
6. Abra uma página em `https://lichess.org/`, `https://www.chess.com/` ou `https://chat.restream.io/`.

O painel `xadrez.live` deve aparecer no canto inferior direito. Fluxo básico:

1. Clique em `Nova sessão` no começo da live.
2. No Puzzle do Dia, clique em `Puzzle do dia`; o userscript também exporta o timestamp desse clique para a timeline.
3. Em cada puzzle da streak, clique em `Add puzzle`.
4. Ao terminar uma sequência, clique em `Fechar tentativa` e informe quantos puzzles contam como resolvidos.
5. Em cada partida, abra a página da partida no Lichess ou no Chess.com e clique em `Add partida`.
6. Use `Practice notes` no meio da sessão, depois dos puzzles/estudos e antes da rapid, para registrar aprendizados, temas e alertas em primeira pessoa. O envio de `Practice notes` também exporta `practice_notes_recorded_at` (relógio de parede ISO) e `practice_notes_event = "practice_end"`; o wrapup converte esse marcador para o tempo relativo da live usando o início real do YouTube. Observações gerais devem ir no paste final do wrapup, não no userscript.
7. Ao fim da live, abra o chat do Restream e role o histórico carregado se necessário. A tela de admin tende a ser melhor para isso; o embed usado no OBS também é suportado, mas pode ter só as mensagens recentes carregadas.
8. Clique em `Save TOML` e salve como `data/fcz/wrap_inbox/NNNN.toml`.
9. No chat do Restream, clique em `Save chat JSON` e salve como `data/fcz/wrap_inbox/NNNN-chat.json`.
10. Rode `just wrap-session NNNN` para aplicar o TOML, importar o chat, derivar os agradecimentos do próprio chat, preencher duração pelo YouTube e ratings pelo Lichess, gerar timeline/capivaradas, validar a sessão e fazer build.

Os botões `Copy TOML` e `Copy chat JSON` continuam disponíveis como fallback, mas o caminho normal do wrapup deve usar arquivos em `data/fcz/wrap_inbox/` para evitar perda de dados no clipboard ou no histórico do chat.

Os apoiadores coletados pelo Restream entram como metadata:

```toml
[[extra.supporters]]
platform = "YouTube"
name = "@mchessters"
url = "https://www.youtube.com/@mchessters"
```

O template da sessão renderiza essa metadata como `Agradecimentos`, e `scripts/update_supporters.py` usa tanto `[[extra.supporters]]` quanto a seção Markdown antiga `## Agradecimentos` para gerar `data/supporters.toml`.

## Publicar no GitHub Pages

O workflow em `.github/workflows/pages.yml` builda o site com Zola e publica o diretório `public`.

No GitHub, abra as configurações do repositório e habilite Pages usando **GitHub Actions** como source.

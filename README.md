# xadrez.live

Site estático mínimo em Zola para o diário pessoal de lives de xadrez em [xadrez.live](https://xadrez.live/).

Visão geral do sistema e da motivação: [Meu sistema de apoio a streamers de xadrez e como ele vem evoluindo](https://lichess.org/@/fcz/blog/meu-sistema-de-apoio-a-streamers-de-xadrez-e-como-ele-vem-evoluindo/OQJjy0BY).

## Fluxo rotineiro

O ponto de entrada principal para manutenção diária é:

```sh
just menu
```

O menu cobre quase todo o fluxo normal:

- **Pre-wrap recente**: depois que o VOD termina, resgata chat do YouTube/Twitch/Restream, baixa transcrições, alinha timestamps, gera candidatos de highlights, atualiza apoiadores e reconstrói o site com busca.
- **Wrapup da sessão**: aplica TOML e JSON exportados pelo userscript, importa chat, preenche duração/ratings, busca análise do Lichess, gera capivaradas, escolhe resumo/título/hook/bullets, publica metadados no YouTube, gera thumbnail, agenda a próxima sessão e faz build.
- **Calibrar offset Lichess**: ajusta o offset entre vídeo e partidas/puzzles quando a timeline de capivaradas precisa ser refinada.
- **Transcrever com Faster Whisper**: roda a transcrição local mais lenta para uma sessão específica.
- **Realinhar e gerar highlights**: refaz alinhamento e candidatos de highlights depois de uma transcrição melhor.

Os comandos diretos continuam disponíveis para automação ou para pular o menu:

```sh
just pre-wrap 5
just wrap-session 0070
just calibrate-session-capivaradas 0069
just import-faster-whisper-transcript 0069
just realign-highlights 0069
```

## Desenvolvimento local

Dependências principais:

- Zola para o site estático.
- `just` para os fluxos do projeto.
- Python 3 para scripts de importação, wrapup e validação.
- Node/npm ou `npx` para gerar o índice Pagefind.
- ImageMagick para thumbnails.
- `yt-dlp` para baixar chat/transcrições/áudio quando necessário.
- `gum` é opcional, mas melhora menus e prompts interativos.

Instalação do Zola:

```sh
# macOS
brew install zola

# Arch Linux
sudo pacman -S zola
```

Outras opções estão na documentação oficial do Zola: <https://www.getzola.org/documentation/getting-started/installation/>

Comandos úteis:

```sh
just serve
just build
just build-search
just test
```

`just serve` roda o build, gera o índice Pagefind e sobe o site local. `just build` é a verificação focada depois de mudanças em `content/`, `templates/`, `static/`, `config.toml` ou deploy.

## Sessões

As páginas ficam em `content/fcz/NNNN.md`. A criação/agendamento normal usa:

```sh
just schedule-next-session 0071 --date 2026-08-25 --time 09:00 --youtube YOUTUBE_VIDEO_ID
```

O atalho antigo ainda existe para criar uma sessão com valores padrão:

```sh
just init-session 0071
```

Cada sessão usa front matter TOML. Campos vazios não aparecem na página. Os campos mais importantes são `youtube_video_id`, `time`, `status`, `status_tone`, `description`, `summary_title`, `games`, `practice_sets`, `thumbnail_notes` e `og_image`.

Status comuns:

```toml
status = "marcada para 09:00"
status_tone = "scheduled"

status = "ao vivo agora"
status_tone = "live"

status = "encerrada"
status_tone = "ended"
```

### Calibrar timestamps do replay

Quando a timeline de capivaradas fica deslocada em relação ao vídeo, use o menu ou rode diretamente:

```sh
just calibrate-session-capivaradas 0069
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

### Proveniência editorial

Blocos editoriais produzidos durante o wrapup podem registrar sua proveniência no front matter, em `[extra.editorial]` e `[[extra.editorial.provenance]]`. Cada entrada deve indicar o `field` afetado (`description`, `summary_title`, `agenda`, `notes` ou `thumbnail_notes`), as `sources` usadas, e os flags `ai_assisted` e `human_reviewed`.

Notas no campo `note` de uma partida devem registrar `note_author`, `note_origin` e `note_ai_assisted`. Quando forem escritas pelo streamer durante a análise ao vivo, use `note_origin = "human_live_analysis"` e `note_ai_assisted = false`; elas são fontes primárias humanas, mesmo quando depois alimentam uma síntese editorial assistida por IA.

Use fontes estáveis e separadas: `user_notes`, `game_notes`, `lichess_game_note`, `chat_context`, `chat_replay`, `transcript`, `lichess_analysis` e `lichess_practice`. Para sessões antigas cuja origem precisou ser reconstruída, use `provenance_status = "reconstructed"`; para sessões novas, prefira `verified` quando a trilha foi registrada durante o wrapup.

## Thumbnails

O fluxo normal gera e registra thumbnails pelas receitas:

```sh
just pre-thumb 0071
just post-thumb 0070
just youtube-thumbnail 0070
```

`pre-thumb` cria a thumbnail pré-live local e envia para o YouTube. `post-thumb` cria a thumbnail pós-live a partir dos dados da sessão. `youtube-thumbnail` reenvia a imagem registrada em `og_image` quando necessário.

Também existe um fluxo de prompt manual para usar com ChatGPT Web:

```sh
just thumbnail-prompt 0070 pre
just thumbnail-prompt 0070 post
```

Para otimizar uma imagem manual antes de usá-la como preview social/Twitter:

```sh
just thumbnail-optimize static/fcz/thumbnails/20260616-pre-thumb.png static/fcz/thumbnails/20260616-pre-thumb.jpg
```

Referencie a imagem otimizada no front matter:

```toml
og_image = "/fcz/thumbnails/20260616-pre-thumb.jpg"
```

O arquivo em `og_image` é usado só nas tags Open Graph/Twitter; ele não aparece no corpo da página.

## Revisão editorial

Para procurar erros de ortografia nos textos editoriais, instale o dicionário brasileiro do Hunspell e rode:

```bash
sudo pacman -S hunspell-en_us
yay -S hunspell-pt-br
just check-editorial-spelling
```

O comando não altera arquivos. Para revisar suspeitas interativamente, use `just review-editorial-spelling`. Aprovações ficam em `data/editorial_spelling_approvals.json`; para testar ou aplicar essas aprovações, use `just apply-editorial-spelling` ou `just apply-editorial-spelling --write`.

## Coletar dados da live no Lichess

Durante a live, use o userscript local em `tools/userscripts/xadrez-live-lichess-collector.user.js` para reduzir copia/cola de URLs do Lichess, do Chess.com e do chat do Restream. Ele adiciona um painel flutuante em `lichess.org`, `chess.com` e `chat.restream.io` com botões para:

- adicionar a URL do puzzle atual
- registrar a URL do Puzzle do Dia separadamente
- fechar uma tentativa de streak
- adicionar a URL da partida atual no Lichess ou no Chess.com
- registrar notas gerais e notas específicas da prática de puzzles antes da rapid, separadas no TOML do wrapup
- extrair usernames do chat do Restream e incluir os apoiadores no mesmo TOML da sessão
- copiar um JSON do replay de chat carregado no Restream para importar mais cedo no site
- salvar ou copiar um bloco TOML pronto para o wrapup da sessão

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
4. Para Puzzle Streak, use `Add streak` para capturar a lista atual de puzzles e resultados; como uma streak pode atravessar dias, ela não gera início/fim na timeline. Se a lista automática não estiver disponível, use `Add puzzle`/`Finish streak` como fallback manual. Para Puzzle Storm, use `Start storm` no começo e `Add storm` na tela final; o userscript captura score, puzzles, resultado, tempo e rating de cada puzzle.
5. Em cada partida, abra a página da partida no Lichess ou no Chess.com e clique em `Add partida`.
6. Use `Practice notes` no meio da sessão, depois dos puzzles/estudos e antes da rapid, para registrar aprendizados, temas e alertas em primeira pessoa. O envio de `Practice notes` também exporta `practice_notes_recorded_at` (relógio de parede ISO) e `practice_notes_event = "practice_end"`; o wrapup converte esse marcador para o tempo relativo da live usando o início real do YouTube. Observações gerais devem ir no paste final do wrapup, não no userscript.
7. Ao fim da live, abra o chat do Restream e role o histórico carregado se necessário. A tela de admin tende a ser melhor para isso; o embed usado no OBS também é suportado, mas pode ter só as mensagens recentes carregadas.
8. Clique em `Save TOML`; o fluxo aceita `data/fcz/wrap_inbox/NNNN.toml` ou o download padrão em `~/Downloads/NNNN.toml`.
9. No chat do Restream, clique em `Save chat JSON`; o fluxo aceita `data/fcz/wrap_inbox/NNNN-chat.json` ou `~/Downloads/NNNN-chat.json`.
10. Rode `just wrap-session NNNN` para aplicar o TOML, importar o chat, derivar os agradecimentos do próprio chat, preencher duração pelo YouTube e ratings pelo Lichess, gerar timeline/capivaradas, escolher título/hook/bullets de thumbnail, gerar thumbnail quando necessário, publicar metadados no YouTube, validar a sessão e fazer build. Use `--skip-youtube-finish` quando quiser apenas importar/validar sem publicar.

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

## Licença

Este projeto é licenciado sob a GNU Affero General Public License v3.0. Veja [LICENSE](LICENSE).

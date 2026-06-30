# xadrez.live

Site estático mínimo em Zola para o diário pessoal de lives de xadrez em `xadrez.live`.

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

Durante a live, use o userscript local em `tools/userscripts/xadrez-live-lichess-collector.user.js` para reduzir copia/cola de URLs do Lichess e do Chess.com. Ele adiciona um painel flutuante em `lichess.org` e `chess.com` com botões para:

- adicionar a URL do puzzle atual
- registrar a URL do Puzzle do Dia separadamente
- fechar uma tentativa de streak
- adicionar a URL da partida atual no Lichess ou no Chess.com
- registrar notas soltas para orientar a descrição principal no wrapup
- copiar um bloco TOML pronto para colar no front matter da sessão

Os dados ficam só no `localStorage` do navegador. Não há servidor, login externo nem envio de dados para fora.

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
6. Abra uma página em `https://lichess.org/` ou `https://www.chess.com/`.

O painel `xadrez.live` deve aparecer no canto inferior direito. Fluxo básico:

1. Clique em `Nova sessão` no começo da live.
2. No Puzzle do Dia, clique em `Puzzle do dia`.
3. Em cada puzzle da streak, clique em `Add puzzle`.
4. Ao terminar uma sequência, clique em `Fechar tentativa` e informe quantos puzzles contam como resolvidos.
5. Em cada partida, abra a página da partida no Lichess ou no Chess.com e clique em `Add partida`.
6. Use `Notes` para registrar observações que devem entrar na descrição principal do wrapup.
7. Clique em `Copiar TOML` e cole o bloco no front matter da sessão no GitHub.

## Publicar no GitHub Pages

O workflow em `.github/workflows/pages.yml` builda o site com Zola e publica o diretório `public`.

No GitHub, abra as configurações do repositório e habilite Pages usando **GitHub Actions** como source.

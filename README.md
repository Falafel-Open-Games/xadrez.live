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

## Publicar no GitHub Pages

O workflow em `.github/workflows/pages.yml` builda o site com Zola e publica o diretório `public`.

No GitHub, abra as configurações do repositório e habilite Pages usando **GitHub Actions** como source.

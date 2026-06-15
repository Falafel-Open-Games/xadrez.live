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

## Criar a próxima sessão

Copie o arquivo atual:

```sh
cp content/fcz/0010.md content/fcz/0011.md
```

Depois edite `content/fcz/0011.md`, atualizando `title`, `session_number`, `youtube_video_id`, `date`, `status`, `status_tone`, `tagline` e `description`.

## Publicar no GitHub Pages

O workflow em `.github/workflows/pages.yml` builda o site com Zola e publica o diretório `public`.

No GitHub, abra as configurações do repositório e habilite Pages usando **GitHub Actions** como source.

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    label: str
    description: str
    key: str


ACTIONS = [
    Action(
        "Pre-wrap recente",
        "resgatar chat e transcricoes do YouTube depois que o VOD terminar",
        "pre-wrap",
    ),
    Action(
        "Atualizar capivaradas",
        "buscar analise do Lichess e gerar capivaradas de uma sessao",
        "capivaradas",
    ),
    Action(
        "Calibrar offset Lichess",
        "ajustar offset e regenerar capivaradas da sessao",
        "calibrate-offset",
    ),
    Action(
        "Transcrever com Faster Whisper",
        "job local lento/manual para uma sessao",
        "faster-whisper",
    ),
    Action(
        "Realinhar e gerar highlights",
        "rodar alinhamento e highlights depois que Faster Whisper terminar",
        "realign-highlights",
    ),
    Action(
        "Finalizar YouTube",
        "escolher titulo/hook, publicar descricao/capitulos e thumbnail",
        "youtube-finish",
    ),
    Action(
        "Listar comandos avancados",
        "mostrar todos os recipes do justfile",
        "list",
    ),
]


def run(command: list[str]) -> int:
    print(f"\n$ {' '.join(command)}\n")
    return subprocess.call(command)


def has_gum() -> bool:
    return shutil.which("gum") is not None


def prompt(label: str, default: str = "") -> str:
    if has_gum():
        command = ["gum", "input", "--prompt", f"{label}: "]
        if default:
            command.extend(["--value", default])
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE, check=False)
        if result.returncode != 0:
            return ""
        return result.stdout.strip() or default

    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def confirm(message: str) -> bool:
    if has_gum():
        return subprocess.run(["gum", "confirm", message], check=False).returncode == 0
    return prompt(f"{message} Digite SIM para iniciar", "") == "SIM"


def choose_with_gum() -> Action | None:
    labels = [f"{index + 1}. {action.label} - {action.description}" for index, action in enumerate(ACTIONS)]
    result = subprocess.run(
        ["gum", "choose", "--header", "xadrez.live rotina diaria", *labels],
        text=True,
        stdout=subprocess.PIPE,
        check=False,
    )
    choice = result.stdout.strip()
    if result.returncode != 0 or not choice:
        return None
    for index, action in enumerate(ACTIONS, start=1):
        if choice.startswith(f"{index}. "):
            return action
    return None


def choose_with_prompt() -> Action | None:
    print("xadrez.live rotina diaria\n")
    for index, action in enumerate(ACTIONS, start=1):
        print(f"{index}. {action.label}")
        print(f"   {action.description}")
    choice = prompt("\nEscolha", "1")
    if not choice.isdigit():
        return None
    index = int(choice)
    if not 1 <= index <= len(ACTIONS):
        return None
    return ACTIONS[index - 1]


def choose_action() -> Action | None:
    if has_gum():
        return choose_with_gum()
    return choose_with_prompt()


def command_for(action: Action) -> list[str] | None:
    if action.key == "pre-wrap":
        recent = prompt("RECENT", "5")
        return ["just", "pre-wrap", recent]

    if action.key == "capivaradas":
        session = prompt("Sessao, ex. 0052")
        if not session:
            return None
        return ["just", "update-session-capivaradas", session]

    if action.key == "calibrate-offset":
        session = prompt("Sessao, ex. 0052")
        if not session:
            return None
        return ["just", "calibrate-session-capivaradas", session]

    if action.key == "faster-whisper":
        session = prompt("Sessao, ex. 0052")
        if not session:
            return None
        if not confirm("Faster Whisper e lento e pode levar dezenas de minutos. Iniciar agora?"):
            print("Cancelado.")
            return None
        return ["just", "import-faster-whisper-transcript", session]

    if action.key == "realign-highlights":
        session = prompt("Sessao, ex. 0052")
        if not session:
            return None
        return ["just", "realign-highlights", session]

    if action.key == "youtube-finish":
        session = prompt("Sessao, ex. 0052")
        if not session:
            return None
        if confirm("Escolher/publicar titulo agora?"):
            return ["just", "youtube-finish-session", session]
        print("Pulando titulo.")
        return ["just", "youtube-finish-session-skip-title", session]

    if action.key == "list":
        return ["just", "--list"]

    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Small interactive menu for common xadrez.live daily maintenance.")
    parser.add_argument("--list-actions", action="store_true", help="Print menu actions without prompting.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.list_actions:
        for action in ACTIONS:
            print(f"{action.key}\t{action.label}\t{action.description}")
        return 0

    action = choose_action()
    if action is None:
        print("Nenhuma acao selecionada.")
        return 1

    command = command_for(action)
    if command is None:
        return 1
    return run(command)


if __name__ == "__main__":
    raise SystemExit(main())

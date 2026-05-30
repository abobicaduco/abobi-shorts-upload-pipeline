# -*- coding: utf-8 -*-
"""PT-BR YouTube thumbnail prompt templates (Alanzoka / Bistecon style)."""
from __future__ import annotations

from typing import Sequence

# Slot themes per game — index wraps if count > len(themes)
GAME_THEMES: dict[str, list[str]] = {
    "Fortnite Mobile": [
        "VITÓRIA ÉPICA — texto grande amarelo, explosão de cores, loot no fundo",
        "BUILD INSANO — construção rápida, setas neon, tensão competitiva",
        "CAOS TOTAL — muitos inimigos, contraste alto, expressão chocada",
        "CLUTCH IMPOSSÍVEL — último jogador, contagem regressiva visual",
        "LOOT LENDÁRIO — item raro brilhando, rosto em close com olhos arregalados",
        "FAIL ENGRAÇADO — momento engraçado, texto vermelho impactante",
    ],
    "Granny 2": [
        "FUGA DA GRANNY — terror com humor, texto branco sangrento estilizado",
        "SUSTO REAL — jump scare, rosto gritando, fundo escuro",
        "STEALTH PERFEITO — silêncio tenso, olhos arregalados, sombra da Granny",
        "ESCONDE-ESCONDE — armário ou baú, seta apontando perigo",
        "FINAL SECRETO — final alternativo, texto dourado misterioso",
    ],
}

DEFAULT_THEMES: list[str] = [
    "MOMENTO ÉPICO — vitória ou jogada insana, texto PT-BR grande",
    "FAIL ENGRAÇADO — expressão exagerada, texto vermelho",
    "DESAFIO INSANO — tensão máxima, cores neon",
    "REAÇÃO CHOCADA — close no rosto, fundo borrado do gameplay",
]

STYLE_BLOCK = """
Estilo visual (referência brasileira: Alanzoka, Bistecon, Cellbit):
- Thumbnail YouTube 16:9, alto contraste, cores saturadas (roxo/azul neon + amarelo/vermelho para CTA).
- Texto em PORTUGUÊS DO BRASIL: máximo 3–4 palavras, fonte grossa, contorno preto, legível no celular.
- Rosto humano em destaque (use a foto de referência anexada como identidade do criador — mantenha traços reconhecíveis).
- Fundo: gameplay borrado ou cena do jogo sem logos oficiais registrados.
- Composição dinâmica, bordas brilhantes, setas ou círculos opcionais para foco.
- Proibido: gore realista, texto ilegível, mais de 3 linhas de texto, marcas registradas oficiais.
""".strip()


def themes_for_game(game: str) -> list[str]:
    key = game.strip()
    for name, themes in GAME_THEMES.items():
        if name.lower() == key.lower():
            return themes
    return DEFAULT_THEMES


def build_prompt(
    *,
    game: str,
    slot_index: int,
    video_stem: str,
    channel: str = "@abobicaduco",
) -> str:
    """Build a multimodal text prompt for one thumbnail slot (0-based index)."""
    themes = themes_for_game(game)
    theme = themes[slot_index % len(themes)]
    return f"""
Crie UMA thumbnail de YouTube pronta para publicação.

Jogo: {game}
Vídeo/arquivo: {video_stem}
Canal: {channel}
Tema desta peça: {theme}

{STYLE_BLOCK}

Entregue apenas a imagem final (sem explicação longa).
""".strip()


def list_known_games() -> Sequence[str]:
    return tuple(GAME_THEMES.keys())

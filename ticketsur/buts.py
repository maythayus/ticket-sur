"""Buts attendus de chaque equipe, deduits des cotes 1 N 2 et plus/moins de 2.5 buts.

Le total de buts d'un match suit une loi de Poisson dont la moyenne se lit directement
sur la cote plus/moins de 2.5 ; l'ecart entre les deux equipes se lit sur le 1 N 2. De
ces deux nombres decoulent les marches que la source ne cote pas : « les deux equipes
marquent », et les buts d'une equipe pour estimer un buteur. Le biais du modele (scores
nuls sous-estimes) est corrige ensuite par la calibration, comme pour les autres marches.
"""

from __future__ import annotations

import math
from functools import lru_cache

MAX_BUTS = 10


def _loi(moyenne: float) -> list[float]:
    probas = [math.exp(-moyenne)]
    for k in range(1, MAX_BUTS + 1):
        probas.append(probas[-1] * moyenne / k)
    return probas


def _ecart(dom: float, ext: float) -> float:
    """P(victoire domicile) - P(victoire exterieur)."""
    a, b = _loi(dom), _loi(ext)
    cumul_b = [sum(b[: i + 1]) for i in range(len(b))]
    cumul_a = [sum(a[: i + 1]) for i in range(len(a))]
    p1 = sum(a[i] * cumul_b[i - 1] for i in range(1, len(a)))
    p2 = sum(b[i] * cumul_a[i - 1] for i in range(1, len(b)))
    return p1 - p2


def _bissection(fonction, bas: float, haut: float, cible: float, pas: int = 30) -> float:
    """Racine de fonction(x) = cible, fonction croissante sur [bas, haut]."""
    for _ in range(pas):
        milieu = (bas + haut) / 2
        if fonction(milieu) < cible:
            bas = milieu
        else:
            haut = milieu
    return (bas + haut) / 2


@lru_cache(maxsize=200_000)
def attendus(p1: float, p2: float, plus_2_5: float) -> tuple[float, float]:
    """Buts attendus (domicile, exterieur) reproduisant les probabilites du marche."""

    def plus_de_2(total: float) -> float:
        return 1 - math.exp(-total) * (1 + total + total * total / 2)

    total = _bissection(plus_de_2, 0.2, 7.0, plus_2_5)
    marge = total - 0.02
    ecart = _bissection(lambda d: _ecart((total + d) / 2, (total - d) / 2), -marge, marge, p1 - p2, 22)
    return (total + ecart) / 2, (total - ecart) / 2


def deux_marquent(dom: float, ext: float) -> float:
    return (1 - math.exp(-dom)) * (1 - math.exp(-ext))

"""Calibration : ce que valent vraiment les probabilites du marche.

Pour chaque marche, les probabilites du marche sont confrontees aux resultats de
l'historique : « 80 % annonce » gagne-t-il vraiment 8 fois sur 10 ? La courbe obtenue
est monotone (regression isotonique) : une probabilite plus haute du marche ne peut pas
donner une probabilite reelle plus basse.
"""

from __future__ import annotations

import json
from bisect import bisect_left
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from ticketsur.donnees import Match
from ticketsur.marches import MARCHES, gagne, probas_justes


@dataclass
class Courbe:
    """Points (probabilite du marche, taux de reussite reel, effectif), p croissant."""

    points: list[tuple[float, float, int]]

    def __call__(self, proba: float) -> float:
        abscisses = [p for p, _, _ in self.points]
        i = bisect_left(abscisses, proba)
        # Hors de la plage observee, aucune donnee ne justifie mieux que le marche :
        # on garde l'ecart du point extreme au lieu de prolonger son taux a plat.
        if i == 0:
            p0, t0, _ = self.points[0]
            return min(max(proba + t0 - p0, 0.001), 0.999)
        if i == len(self.points):
            p1, t1, _ = self.points[-1]
            return min(max(proba + t1 - p1, 0.001), 0.999)
        (p0, t0, _), (p1, t1, _) = self.points[i - 1], self.points[i]
        return t0 + (t1 - t0) * (proba - p0) / (p1 - p0) if p1 > p0 else t1

    def effectif_proche(self, proba: float) -> int:
        """Nombre de matchs historiques derriere le point le plus proche."""
        return min(self.points, key=lambda point: abs(point[0] - proba))[2]


def ajuster(paires: list[tuple[float, bool]], bacs: int = 40) -> Courbe:
    """Bacs d'effectif egal, puis fusion des voisins jusqu'a obtenir une courbe croissante."""
    paires = sorted(paires)
    taille = max(1, len(paires) // bacs)
    blocs: list[list[float]] = []  # [somme p, somme reussites, effectif]
    for debut in range(0, len(paires), taille):
        tranche = paires[debut : debut + taille]
        bloc = [sum(p for p, _ in tranche), sum(g for _, g in tranche), len(tranche)]
        if blocs and len(tranche) < taille:
            # Reste de la division : quelques matchs seuls feraient un point extreme
            # au taux aberrant, celui-la meme que le selecteur irait chercher.
            blocs[-1] = [a + b for a, b in zip(blocs[-1], bloc, strict=True)]
        else:
            blocs.append(bloc)
    # Pool Adjacent Violators : un bloc moins reussi que son predecesseur est fusionne.
    pile: list[list[float]] = []
    for bloc in blocs:
        pile.append(bloc)
        while len(pile) > 1 and pile[-2][1] / pile[-2][2] >= pile[-1][1] / pile[-1][2]:
            haut = pile.pop()
            pile[-1] = [a + b for a, b in zip(pile[-1], haut, strict=True)]
    return Courbe([(s / n, r / n, int(n)) for s, r, n in pile])


@dataclass
class Calibration:
    courbes: dict[str, Courbe] = field(default_factory=dict)
    matchs: int = 0

    def proba(self, marche: str, proba_marche: float) -> float:
        courbe = self.courbes.get(marche)
        return courbe(proba_marche) if courbe else proba_marche

    def sauver(self, chemin: Path) -> None:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        contenu = {
            "matchs": self.matchs,
            "courbes": {m: c.points for m, c in self.courbes.items()},
        }
        chemin.write_text(json.dumps(contenu), encoding="utf-8")

    @classmethod
    def charger(cls, chemin: Path) -> Calibration:
        contenu = json.loads(chemin.read_text(encoding="utf-8"))
        courbes = {
            marche: Courbe([tuple(point) for point in points])
            for marche, points in contenu["courbes"].items()
        }
        return cls(courbes, contenu["matchs"])


def calibrer(matchs: Iterable[Match]) -> Calibration:
    paires: dict[str, list[tuple[float, bool]]] = {marche: [] for marche in MARCHES}
    total = 0
    for match in matchs:
        if not match.buts:
            continue
        total += 1
        for marche, proba in probas_justes(match.cotes).items():
            paires[marche].append((proba, gagne(marche, *match.buts)))
    courbes = {marche: ajuster(liste) for marche, liste in paires.items() if len(liste) >= 400}
    return Calibration(courbes, total)

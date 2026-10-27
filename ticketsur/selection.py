"""Construction du ticket : le plus probable dans une fourchette de cote."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from itertools import combinations

from ticketsur import config
from ticketsur.calibration import Calibration
from ticketsur.donnees import Match
from ticketsur.marches import COTES_ESTIMEES, cote, libelle, probas_justes


@dataclass
class Selection:
    match: Match
    marche: str
    proba: float  # calibree sur l'historique
    proba_marche: float
    cote: float

    @property
    def cote_estimee(self) -> bool:
        return self.marche in COTES_ESTIMEES

    @property
    def libelle(self) -> str:
        return libelle(self.marche, self.match.domicile, self.match.exterieur)

    @property
    def cle(self) -> tuple:
        return (*self.match.cle, self.marche)


@dataclass
class Ticket:
    selections: list[Selection] = field(default_factory=list)

    @property
    def proba(self) -> float:
        return math.prod(s.proba for s in self.selections)

    @property
    def cote(self) -> float:
        return math.prod(s.cote for s in self.selections)


def candidats(
    matchs: Iterable[Match], calibration: Calibration, cote_min_selection: float
) -> list[Selection]:
    """Toutes les selections jouables, de la plus probable a la moins probable."""
    liste: list[Selection] = []
    for match in matchs:
        for marche, proba_marche in probas_justes(match.cotes).items():
            proba = calibration.proba(marche, proba_marche)
            if marche in COTES_ESTIMEES:
                # Pas de cote dans la source : celle qu'un bookmaker proposerait a peu
                # pres, marge comprise. A verifier avant de jouer.
                valeur = config.RETOUR_ESTIME / proba
            else:
                valeur = cote(match.cotes, marche)
            if valeur is None or valeur < cote_min_selection:
                continue
            liste.append(Selection(match, marche, proba, proba_marche, valeur))
    liste.sort(key=lambda s: s.proba, reverse=True)
    return liste


def meilleurs_tickets(
    selections: list[Selection],
    *,
    cote_min: float,
    cote_max: float,
    max_selections: int,
    nombre: int = 1,
    exclues: set[tuple] | None = None,
) -> list[Ticket]:
    """Les `nombre` tickets les plus probables dont la cote tombe dans la fourchette.

    Une seule selection par match : deux marches d'un meme match sont lies, multiplier
    leurs probabilites mentirait sur la chance reelle du ticket.
    """
    exclues = exclues or set()
    pool = [s for s in selections if s.cle not in exclues]
    retenus: list[tuple[float, tuple[Selection, ...]]] = []
    for taille in range(1, max_selections + 1):
        # Au-dela d'une selection, seules les plus probables peuvent former le meilleur
        # ticket : inutile d'enumerer des millions de combinaisons.
        source = pool if taille == 1 else pool[: 120 if taille == 2 else 45]
        for combo in combinations(source, taille):
            cote_ticket = math.prod(s.cote for s in combo)
            if not cote_min <= cote_ticket <= cote_max:
                continue
            if taille > 1 and len({s.match.cle for s in combo}) < taille:
                continue
            retenus.append((math.prod(s.proba for s in combo), combo))
    retenus.sort(key=lambda item: item[0], reverse=True)
    return [Ticket(list(combo)) for _, combo in retenus[:nombre]]

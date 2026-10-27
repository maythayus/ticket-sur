"""Backtest en avant : chaque saison est jouee avec une calibration apprise avant elle.

Jamais de resultat futur dans la calibration : c'est ce qui rend les chiffres honnetes.
Un ticket par jour de match, construit avec la meme regle que `ticket jour`.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from ticketsur.calibration import calibrer
from ticketsur.donnees import Match, saison_de
from ticketsur.marches import gagne
from ticketsur.selection import candidats, meilleurs_tickets


@dataclass
class Regle:
    cote_min: float
    cote_max: float
    max_selections: int
    cote_min_selection: float


@dataclass
class Bilan:
    tickets: int = 0
    gagnes: int = 0
    proba_prevue: float = 0.0  # somme des probabilites annoncees
    gain_net: float = 0.0  # mise de 1 par ticket
    serie_noire: int = 0  # plus longue suite de tickets perdus
    par_saison: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def taux(self) -> float:
        return self.gagnes / self.tickets if self.tickets else 0.0

    @property
    def taux_prevu(self) -> float:
        return self.proba_prevue / self.tickets if self.tickets else 0.0

    @property
    def roi(self) -> float:
        return self.gain_net / self.tickets if self.tickets else 0.0


def backtest(matchs: list[Match], saisons_test: list[str], regle: Regle, decote: float) -> Bilan:
    par_saison: dict[str, list[Match]] = defaultdict(list)
    for match in matchs:
        par_saison[saison_de(match.jour)].append(match)

    bilan = Bilan()
    serie = 0
    for saison in saisons_test:
        anterieurs = [m for s, liste in par_saison.items() if s < saison for m in liste]
        if not anterieurs or not par_saison.get(saison):
            continue
        calibration = calibrer(anterieurs)
        par_jour: dict = defaultdict(list)
        for match in par_saison[saison]:
            par_jour[match.jour].append(match)
        joues = gagnes = 0
        for jour in sorted(par_jour):
            selections = candidats(par_jour[jour], calibration, regle.cote_min_selection)
            tickets = meilleurs_tickets(
                selections,
                cote_min=regle.cote_min,
                cote_max=regle.cote_max,
                max_selections=regle.max_selections,
            )
            if not tickets:
                continue
            ticket = tickets[0]
            reussi = all(gagne(s.marche, *s.match.buts) for s in ticket.selections)
            paiement = math.prod(s.cote * decote for s in ticket.selections)
            joues += 1
            gagnes += reussi
            bilan.proba_prevue += ticket.proba
            bilan.gain_net += (paiement - 1) if reussi else -1
            serie = 0 if reussi else serie + 1
            bilan.serie_noire = max(bilan.serie_noire, serie)
        bilan.tickets += joues
        bilan.gagnes += gagnes
        bilan.par_saison[saison] = (joues, gagnes)
    return bilan

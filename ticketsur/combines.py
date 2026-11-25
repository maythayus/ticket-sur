"""Combines a composition imposee : 4 « les deux marquent », 2 oui / 2 non, panaches 6 et 8.

Un combine long perd plus souvent qu'il ne gagne : c'est le prix du gain affiche. Ce
module ne promet pas l'inverse ; il rend le risque calculable. Chaque selection porte
une probabilite calibree sur l'historique, le combine en est le produit (une selection
par match, les issues d'une meme rencontre etant liees), et `backtest_combines` mesure
sur les saisons passees si la reussite annoncee est la reussite obtenue.

Le choix est glouton : les familles les plus rares d'abord (la mi-temps), puis les
autres, en prenant a chaque fois la selection la plus probable d'un match encore libre.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from ticketsur import config
from ticketsur.calibration import calibrer
from ticketsur.donnees import Match, saison_de
from ticketsur.marches import gagne
from ticketsur.selection import Selection, Ticket, candidats

FAMILLES: dict[str, tuple[str, ...]] = {
    "mi-temps": ("MT1", "MTN", "MT2"),
    "2M": ("2M",),
    "2M-non": ("2M-non",),
    "double chance": ("1N", "N2", "12"),
    "+/- 2.5": ("+2.5", "-2.5"),
}


@dataclass(frozen=True)
class Composition:
    nom: str
    parts: tuple[tuple[str, int], ...]  # (famille, nombre), servies dans cet ordre

    @property
    def taille(self) -> int:
        return sum(n for _, n in self.parts)


COMPOSITIONS = (
    Composition("4 matchs : les 2 marquent (4 oui)", (("2M", 4),)),
    Composition("4 matchs : les 2 marquent (2 oui, 2 non)", (("2M-non", 2), ("2M", 2))),
    Composition(
        "Combiné 6 : mi-temps, double chance, +/- 2.5",
        (("mi-temps", 2), ("double chance", 2), ("+/- 2.5", 2)),
    ),
    Composition(
        "Combiné 8 : mi-temps, double chance, +/- 2.5",
        (("mi-temps", 2), ("double chance", 3), ("+/- 2.5", 3)),
    ),
)

# En dessous, une selection n'apporte rien a un combine sinon du hasard : huit
# selections a 55 % ne passent qu'une fois sur 119. La mi-temps a trois issues et
# beaucoup de nuls a la pause : 45 % y est deja une prediction nette.
PROBA_MIN = {"mi-temps": 0.42}
PROBA_MIN_DEFAUT = 0.55


def construire(
    selections: list[Selection], composition: Composition, exclues: set[tuple] | None = None
) -> Ticket | None:
    """Combine de la composition demandee, ou None s'il manque des selections."""
    exclues = exclues or set()
    pris: set[tuple] = set()
    retenues: list[Selection] = []
    for famille, nombre in composition.parts:
        marches = FAMILLES[famille]
        seuil = PROBA_MIN.get(famille, PROBA_MIN_DEFAUT)
        pool = sorted(
            (
                s
                for s in selections
                if s.marche in marches and s.proba >= seuil and s.cle not in exclues
            ),
            key=lambda s: s.proba,
            reverse=True,
        )
        choisies = 0
        for s in pool:
            if choisies == nombre:
                break
            if s.match.cle in pris:
                continue
            pris.add(s.match.cle)
            retenues.append(s)
            choisies += 1
        if choisies < nombre:
            return None
    retenues.sort(key=lambda s: (s.match.coup_envoi() is None, s.match.coup_envoi() or 0))
    return Ticket(retenues)


def esperance(ticket: Ticket, decote: float = config.DECOTE) -> float:
    """Ce que rend en moyenne 1 € mise, cotes decotees : 0.90 = 10 % de perte."""
    return ticket.proba * math.prod(s.cote * decote for s in ticket.selections)


@dataclass
class BilanCombine:
    tickets: int = 0
    gagnes: int = 0
    proba_prevue: float = 0.0
    gain_net: float = 0.0
    serie_noire: int = 0
    _serie: int = field(default=0, repr=False)

    def ajouter(self, proba: float, reussi: bool, paiement: float) -> None:
        self.tickets += 1
        self.gagnes += reussi
        self.proba_prevue += proba
        self.gain_net += (paiement - 1) if reussi else -1
        self._serie = 0 if reussi else self._serie + 1
        self.serie_noire = max(self.serie_noire, self._serie)

    @property
    def taux(self) -> float:
        return self.gagnes / self.tickets if self.tickets else 0.0

    @property
    def taux_prevu(self) -> float:
        return self.proba_prevue / self.tickets if self.tickets else 0.0

    @property
    def roi(self) -> float:
        return self.gain_net / self.tickets if self.tickets else 0.0


def backtest_combines(
    matchs: list[Match], saisons_test: list[str], decote: float = config.DECOTE
) -> dict[str, BilanCombine]:
    """Chaque composition jouee chaque jour de match ou elle est constructible.

    Calibration apprise sur les seules saisons anterieures, comme `backtest.backtest`.
    Les cotes estimees (les 2 marquent, mi-temps) supposent la marge de `RETOUR_ESTIME` :
    leur gain est une hypothese, leur taux de reussite non.
    """
    par_saison: dict[str, list[Match]] = defaultdict(list)
    for match in matchs:
        par_saison[saison_de(match.jour)].append(match)
    bilans = {c.nom: BilanCombine() for c in COMPOSITIONS}
    for saison in saisons_test:
        anterieurs = [m for s, liste in par_saison.items() if s < saison for m in liste]
        if not anterieurs or not par_saison.get(saison):
            continue
        calibration = calibrer(anterieurs)
        par_jour: dict = defaultdict(list)
        for match in par_saison[saison]:
            if match.buts_mt is not None:
                par_jour[match.jour].append(match)
        for jour in sorted(par_jour):
            selections = candidats(
                par_jour[jour], calibration, config.COTE_MIN_SELECTION, mi_temps=True
            )
            for composition in COMPOSITIONS:
                ticket = construire(selections, composition)
                if not ticket:
                    continue
                reussi = all(
                    gagne(s.marche, *s.match.buts, s.match.buts_mt) for s in ticket.selections
                )
                paiement = math.prod(s.cote * decote for s in ticket.selections)
                bilans[composition.nom].ajouter(ticket.proba, reussi, paiement)
    return bilans

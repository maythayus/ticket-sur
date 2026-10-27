"""Analyse d'un ticket joue chez un bookmaker : ce qu'il vaut, ce qui le plombe.

Les erreurs relevees sur de vrais tickets se repetent : trop de selections, paris
buteur, doubles chances a la mi-temps, sports melanges, mises fortes sur des cotes
hautes. Chaque selection gagne souvent ; c'est le nombre de selections qui fait perdre
le ticket, presque toujours a une selection pres.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from itertools import combinations

from ticketsur import config

# Part de la mise rendue en moyenne par type de pari (ordre de grandeur pour un
# bookmaker francais, dont le retour est plafonne par la loi a 85 % en moyenne).
# La probabilite d'une selection est estimee a retour / cote.
RETOUR: dict[str, float] = {
    "resultat": 0.90,
    "double_chance": 0.90,
    "deux_marquent": 0.88,
    "buts": 0.90,
    "mi_temps": 0.85,
    "buteur": 0.78,
    "combine_maison": 0.80,
    "autre_sport": 0.90,
    "autre": 0.87,
}

# Types ecartes de la version corrigee : marges les plus lourdes, aucun historique pour
# les calibrer.
ECARTES = {"buteur", "mi_temps", "combine_maison", "autre_sport"}

NOMS = {
    "resultat": "1N2",
    "double_chance": "double chance",
    "deux_marquent": "les 2 équipes marquent",
    "buts": "plus/moins de buts",
    "mi_temps": "pari à la mi-temps",
    "buteur": "buteur",
    "combine_maison": "combiné maison (MyMatch, DC + BTTS…)",
    "autre_sport": "autre sport",
    "autre": "autre",
}


def classer(pari: str, sport: str = "football") -> str:
    """Type de pari d'apres son libelle chez le bookmaker."""
    texte = pari.lower()
    if sport and sport.lower() not in ("football", "foot", "soccer"):
        return "autre_sport"
    if re.search(r"set|jeux|tie-break|vainqueur du match", texte) and "mi-temps" not in texte:
        return "autre_sport"
    if "buteur" in texte:
        return "buteur"
    if "mymatch" in texte or ("double chance" in texte and "marquent" in texte) or " et " in texte:
        return "combine_maison"
    if "mi-temps" in texte or "mi temps" in texte:
        return "mi_temps"
    if "marquent" in texte or "marquera" in texte:
        return "deux_marquent"
    if "double chance" in texte:
        return "double_chance"
    if "plus de" in texte or "moins de" in texte or "buts" in texte:
        return "buts"
    if "1n2" in texte or "1/n/2" in texte or "résultat" in texte or "resultat" in texte:
        return "resultat"
    return "autre"


@dataclass
class Jambe:
    match: str
    pari: str
    cote: float
    type: str = "autre"
    resultat: str | None = None  # gagne, perdu ou None si inconnu

    @property
    def proba(self) -> float:
        return min(RETOUR.get(self.type, RETOUR["autre"]) / self.cote, 0.99)


@dataclass
class Billet:
    jambes: list[Jambe] = field(default_factory=list)
    mise: float | None = None
    cote: float | None = None  # celle du bookmaker, boost compris le cas echeant
    boost: float = 0.0  # +2.5 % -> 0.025
    statut: str | None = None  # gagne, perdu, en_cours
    jour: str | None = None
    bookmaker: str | None = None

    @property
    def cote_calculee(self) -> float:
        return math.prod(j.cote for j in self.jambes) if self.jambes else (self.cote or 0.0)

    @property
    def proba(self) -> float:
        if self.jambes:
            return math.prod(j.proba for j in self.jambes)
        return RETOUR["autre"] / self.cote if self.cote else 0.0

    @property
    def esperance(self) -> float:
        """Ce que rapporte en moyenne 1 euro mise sur ce ticket."""
        return self.proba * self.cote_calculee * (1 + self.boost)


@dataclass
class Alerte:
    gravite: str  # grave, attention
    message: str


def diagnostiquer(billet: Billet) -> list[Alerte]:
    alertes: list[Alerte] = []
    n = len(billet.jambes)
    if n > config.MAX_SELECTIONS:
        moyenne = billet.proba ** (1 / n) if n else 0
        alertes.append(Alerte("grave",
            f"{n} sélections : chacune passe en moyenne {moyenne:.0%} du temps, mais il les "
            f"faut toutes ({moyenne:.0%} puissance {n} = {billet.proba:.0%}). Le ticket se perd "
            f"presque toujours à une sélection près."))
    cote = billet.cote_calculee
    if cote > config.COTE_MAX_TICKET * 1.5:
        alertes.append(Alerte("grave",
            f"Cote totale {cote:.2f} : environ 1 chance sur {max(1, round(1 / billet.proba)) if billet.proba else '∞'}."))
    for type_, conseil in (
        ("buteur", "pari buteur : la marge la plus lourde, et un joueur peut sortir à la 60e"),
        ("mi_temps", "pari à la mi-temps : 45 minutes, beaucoup de hasard"),
        ("combine_maison", "combiné maison : deux conditions dans une seule sélection"),
        ("autre_sport", "sport mélangé au foot : aucun historique pour le vérifier ici"),
    ):
        concernees = [j for j in billet.jambes if j.type == type_]
        if concernees:
            noms = ", ".join(j.match for j in concernees[:3])
            alertes.append(Alerte("attention", f"{len(concernees)} {conseil} ({noms})."))
    if billet.boost and n > config.MAX_SELECTIONS:
        perte = 1 - math.prod(RETOUR.get(j.type, RETOUR["autre"]) for j in billet.jambes)
        alertes.append(Alerte("attention",
            f"Boost +{billet.boost:.1%} : la marge cumulée des {n} sélections est d'environ "
            f"{perte:.0%}. Le boost pousse à ajouter des matchs, il ne compense pas."))
    if billet.mise and billet.mise > config.MISE_MAX:
        alertes.append(Alerte("grave",
            f"Mise de {billet.mise:.0f} € au-dessus de ta limite ({config.MISE_MAX:.0f} €)."))
    return alertes


def version_corrigee(billet: Billet) -> Billet | None:
    """Les une ou deux meilleures selections du ticket, comme `ticket jour` les aurait gardees."""
    gardables = [j for j in billet.jambes if j.type not in ECARTES]
    meilleur: tuple[float, tuple[Jambe, ...]] | None = None
    for taille in range(1, min(config.MAX_SELECTIONS, len(gardables)) + 1):
        for combo in combinations(gardables, taille):
            if math.prod(j.cote for j in combo) < config.COTE_MIN_CORRIGEE:
                continue
            proba = math.prod(j.proba for j in combo)
            if meilleur is None or proba > meilleur[0]:
                meilleur = (proba, combo)
    if not meilleur or len(meilleur[1]) == len(billet.jambes):
        return None
    return Billet(list(meilleur[1]), mise=billet.mise)


def issue(billet: Billet) -> str | None:
    """gagne / perdu d'apres les resultats connus des selections, sinon None."""
    resultats = [j.resultat for j in billet.jambes]
    if "perdu" in resultats:
        return "perdu"
    if resultats and all(r == "gagne" for r in resultats):
        return "gagne"
    return None


def depuis_dict(donnees: dict) -> Billet:
    jambes = [
        Jambe(
            match=j.get("match", "?"),
            pari=j.get("pari", ""),
            cote=float(j["cote"]),
            type=j.get("type") or classer(j.get("pari", ""), j.get("sport", "football")),
            resultat=j.get("resultat") if j.get("resultat") in ("gagne", "perdu") else None,
        )
        for j in donnees.get("jambes", [])
        if j.get("cote")
    ]
    return Billet(
        jambes=jambes,
        mise=donnees.get("mise"),
        cote=donnees.get("cote"),
        boost=float(donnees.get("boost") or 0),
        statut=donnees.get("statut"),
        jour=donnees.get("jour"),
        bookmaker=donnees.get("bookmaker"),
    )

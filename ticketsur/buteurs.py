"""Buteurs potentiels : chance de marquer de chaque attaquant probable, et cote a exiger.

Aucun historique de joueurs n'est disponible gratuitement : cette estimation n'est pas
calibree ni backtestee, contrairement au ticket. Elle combine deux choses :

- les buts attendus de l'equipe, lus sur les cotes du match (`buts.attendus`) ;
- la part de ces buts que marque le joueur, d'apres sa saison (trouvee par Claude).

P(marque) = 1 - exp(-buts attendus x part du joueur x temps de jeu). Le pari n'a de
sens que si le bookmaker paie plus que la cote juste 1 / P, ce qui est rare : c'est le
marche ou la marge est la plus lourde.
"""

from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass

from ticketsur import config
from ticketsur.buts import attendus
from ticketsur.donnees import Match, charger_historique, saison_de
from ticketsur.marches import probas_justes
from ticketsur.verification import VerificationImpossible

SCHEMA = {
    "type": "object",
    "properties": {
        "equipes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "equipe": {"type": "string"},
                    "buts_equipe": {"type": "integer", "description": "buts en championnat cette saison"},
                    "joueurs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "nom": {"type": "string"},
                                "buts": {"type": "integer", "description": "buts en championnat cette saison"},
                                "titulaire_probable": {"type": "boolean"},
                                "source": {"type": "string"},
                            },
                            "required": ["nom", "buts", "titulaire_probable", "source"],
                        },
                    },
                },
                "required": ["equipe", "buts_equipe", "joueurs"],
            },
        }
    },
    "required": ["equipes"],
}

# Temps de jeu moyen : un titulaire joue environ les trois quarts du match, un
# remplacant un quart, en comptant les sorties et entrees en jeu.
PRESENCE_TITULAIRE = 0.80
PRESENCE_REMPLACANT = 0.25


@dataclass
class Buteur:
    nom: str
    equipe: str
    match: Match
    proba: float
    titulaire: bool
    buts: int
    source: str

    @property
    def cote_juste(self) -> float:
        return 1 / self.proba


def equipes_offensives(matchs: list[Match], nombre: int) -> list[tuple[Match, str, float]]:
    """Les equipes du jour aux buts attendus les plus eleves."""
    liste: list[tuple[Match, str, float]] = []
    for match in matchs:
        probas = probas_justes(match.cotes)
        if "+2.5" not in probas:
            continue
        dom, ext = attendus(round(probas["1"], 4), round(probas["2"], 4), round(probas["+2.5"], 4))
        liste += [(match, match.domicile, dom), (match, match.exterieur, ext)]
    liste.sort(key=lambda item: item[2], reverse=True)
    return liste[:nombre]


def proba_marque(buts_attendus: float, buts_joueur: int, buts_equipe: int, titulaire: bool) -> float:
    # Part lissee : en debut de saison, 3 buts sur 5 ne font pas un joueur a 60 %.
    part = (buts_joueur + 0.5) / (buts_equipe + 6)
    presence = PRESENCE_TITULAIRE if titulaire else PRESENCE_REMPLACANT
    return 1 - math.exp(-buts_attendus * min(part, 0.6) * presence)


def buts_en_championnat(equipe: str, ligue: str, saison: str) -> int | None:
    """Buts de l'equipe dans son championnat cette saison, d'apres football-data."""
    total, joues = 0, 0
    for m in charger_historique([saison]):
        if m.ligue != ligue or equipe not in (m.domicile, m.exterieur):
            continue
        joues += 1
        total += m.buts[0] if m.domicile == equipe else m.buts[1]
    return total if joues else None


def chercher(matchs: list[Match], nombre_equipes: int = 4) -> list[Buteur]:
    equipes = equipes_offensives(matchs, nombre_equipes)
    if not equipes:
        return []
    lignes = [
        f"- {equipe} (match {m.domicile} - {m.exterieur}, {m.ligue}, {m.jour.strftime('%d/%m/%Y')})"
        for m, equipe, _ in equipes
    ]
    consigne = (
        "Pour chaque equipe ci-dessous, cherche sur le web : le nombre de buts marques par "
        "l'equipe en championnat cette saison, et ses trois meilleurs buteurs en championnat "
        "cette saison (nombre de buts), en indiquant s'ils sont titulaires probables pour ce "
        "match (blessure, suspension, rotation annoncee = false). Donnees de la saison en "
        "cours uniquement ; cite la source. N'invente aucun chiffre : si tu ne trouves pas, "
        "omets le joueur.\n\n" + "\n".join(lignes)
    )
    commande = [
        config.CLAUDE, "-p", consigne,
        "--model", config.CLAUDE_MODELE,
        "--allowedTools", "WebSearch,WebFetch",
        "--output-format", "json",
        "--json-schema", json.dumps(SCHEMA),
    ]
    try:
        sortie = subprocess.run(commande, capture_output=True, text=True,
                                timeout=config.CLAUDE_DELAI, cwd=config.DONNEES, check=False)
        reponse = json.loads(sortie.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        raise VerificationImpossible(f"Recherche des buteurs impossible : {exc}") from exc
    if reponse.get("is_error") or not isinstance(reponse.get("structured_output"), dict):
        raise VerificationImpossible(f"Claude en echec : {str(reponse.get('result'))[:300]}")

    # Trace de la derniere recherche : les chiffres viennent du web, ils se verifient.
    (config.DONNEES / "buteurs-derniere-recherche.json").write_text(
        json.dumps(reponse["structured_output"], ensure_ascii=False, indent=1), encoding="utf-8")
    attendus_par_equipe = {equipe.lower(): (m, lam) for m, equipe, lam in equipes}
    buteurs: list[Buteur] = []
    for bloc in reponse["structured_output"].get("equipes", []):
        cle = next((e for e in attendus_par_equipe
                    if e in bloc.get("equipe", "").lower() or bloc.get("equipe", "").lower() in e), None)
        if cle is None:
            continue
        match, lam = attendus_par_equipe[cle]
        equipe = match.domicile if match.domicile.lower() == cle else match.exterieur
        # Le total de l'equipe vient de nos donnees, pas du web : un total faux trouve en
        # ligne gonflait la part de chaque joueur.
        buts_equipe = buts_en_championnat(equipe, match.ligue, saison_de(match.jour))
        buts_equipe = buts_equipe if buts_equipe is not None else int(bloc["buts_equipe"])
        if sum(int(j["buts"]) for j in bloc.get("joueurs", [])) > buts_equipe:
            continue  # chiffres incoherents : mieux vaut rien qu'une fausse estimation
        for joueur in bloc.get("joueurs", []):
            proba = proba_marque(lam, int(joueur["buts"]), buts_equipe,
                                 bool(joueur["titulaire_probable"]))
            buteurs.append(Buteur(joueur["nom"], bloc["equipe"], match, proba,
                                  bool(joueur["titulaire_probable"]), int(joueur["buts"]),
                                  joueur.get("source", "")))
    buteurs.sort(key=lambda b: b.proba, reverse=True)
    return buteurs

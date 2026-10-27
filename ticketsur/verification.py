"""Contre-verification des selections par Claude Code, en mode non interactif.

Les cotes savent deja beaucoup ; ce qui leur echappe parfois, ce sont les nouvelles
du jour : titulaire blesse la veille, equipe B alignee avant un match europeen, rien a
jouer en fin de saison. Claude cherche sur le web et peut ecarter une selection.

Cette etape n'est pas mesurable par le backtest (l'actualite passee n'est pas
archivee) : son effet reel se lit dans `ticket bilan`.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ticketsur import config
from ticketsur.selection import Selection

SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "verdict": {"type": "string", "enum": ["ok", "risque", "eviter"]},
                    "raison": {"type": "string"},
                },
                "required": ["id", "verdict", "raison"],
            },
        }
    },
    "required": ["verdicts"],
}


class VerificationImpossible(RuntimeError):
    pass


@dataclass
class Verdict:
    verdict: str  # ok, risque, eviter
    raison: str


def _consigne(selections: list[Selection]) -> str:
    lignes = []
    for numero, s in enumerate(selections):
        envoi = s.match.coup_envoi()
        quand = envoi.strftime("%d/%m/%Y %H:%M") if envoi else s.match.jour.strftime("%d/%m/%Y")
        lignes.append(
            f"{numero}. {s.match.domicile} - {s.match.exterieur} ({s.match.ligue}, {quand}) : "
            f"pari « {s.libelle} », cote {s.cote:.2f}, probabilite estimee {s.proba:.0%}"
        )
    return (
        f"Nous sommes le {date.today().strftime('%d/%m/%Y')}. "
        "Tu verifies des selections de paris sportifs avant qu'elles soient jouees. "
        "Les probabilites viennent des cotes du marche, calibrees sur dix saisons : ne les "
        "refais pas. Ton seul travail : chercher sur le web l'actualite recente de chaque "
        "match qui pourrait les rendre fausses.\n\n"
        "A verifier pour chaque match : absences importantes (blessures, suspensions) "
        "annoncees recemment, rotation probable (match de coupe ou d'Europe proche, "
        "titre deja joue), enjeu inhabituel ou absence d'enjeu, conditions exceptionnelles, "
        "changement d'entraineur.\n"
        "Fais au moins une recherche par match, datee (nom des deux equipes, mois et "
        "annee en cours, « blessures », « compo probable », « team news »), dans la "
        "langue du pays du club ; seules les informations de ces derniers jours comptent. "
        "Si la recherche standard ne renvoie que des articles anciens, relance-la en mode "
        "extended avant de conclure.\n\n"
        "Verdicts :\n"
        "- ok : rien de notable, ou rien trouve. Ne pas trouver d'information est un ok.\n"
        "- risque : un element defavorable reel, mais pas determinant.\n"
        "- eviter : un element serieux et source, qui contredit directement le pari.\n"
        "N'invente rien ; cite la source dans la raison (une phrase courte, en francais).\n\n"
        "Selections :\n" + "\n".join(lignes)
    )


def verifier(selections: list[Selection]) -> dict[tuple, Verdict]:
    """Verdict de Claude pour chaque selection, indexe par la cle de la selection."""
    if not selections:
        return {}
    commande = [
        config.CLAUDE,
        "-p",
        _consigne(selections),
        "--model",
        config.CLAUDE_MODELE,
        "--allowedTools",
        "WebSearch,WebFetch",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(SCHEMA),
    ]
    try:
        sortie = subprocess.run(
            commande,
            capture_output=True,
            text=True,
            timeout=config.CLAUDE_DELAI,
            cwd=config.DONNEES,
            check=False,
        )
    except FileNotFoundError as exc:
        raise VerificationImpossible(
            f"Commande Claude introuvable ({config.CLAUDE}) : TICKET_CLAUDE pour la preciser"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise VerificationImpossible("Claude n'a pas repondu dans le delai") from exc
    try:
        reponse = json.loads(sortie.stdout)
    except json.JSONDecodeError as exc:
        message = (sortie.stderr or sortie.stdout).strip()[:300]
        raise VerificationImpossible(f"Reponse illisible de Claude : {message}") from exc
    if reponse.get("is_error") or not isinstance(reponse.get("structured_output"), dict):
        raise VerificationImpossible(f"Claude en echec : {str(reponse.get('result'))[:300]}")

    verdicts: dict[tuple, Verdict] = {}
    for item in reponse["structured_output"].get("verdicts", []):
        numero = item.get("id")
        if isinstance(numero, int) and 0 <= numero < len(selections):
            verdict = item.get("verdict") if item.get("verdict") in ("ok", "risque", "eviter") else "ok"
            verdicts[selections[numero].cle] = Verdict(verdict, str(item.get("raison", "")))
    return verdicts


SCHEMA_CAPTURE = {
    "type": "object",
    "properties": {
        "bookmaker": {"type": "string"},
        "jour": {"type": ["string", "null"], "description": "AAAA-MM-JJ si visible"},
        "mise": {"type": ["number", "null"]},
        "cote": {"type": ["number", "null"], "description": "cote totale affichee"},
        "boost": {"type": "number", "description": "boost combine, 0.025 pour +2,5 %"},
        "statut": {"type": "string", "enum": ["gagne", "perdu", "en_cours", "inconnu"]},
        "jambes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "match": {"type": "string"},
                    "sport": {"type": "string"},
                    "pari": {"type": "string", "description": "type de pari puis selection"},
                    "cote": {"type": "number"},
                    "resultat": {"type": "string", "enum": ["gagne", "perdu", "inconnu"]},
                },
                "required": ["match", "sport", "pari", "cote", "resultat"],
            },
        },
    },
    "required": ["bookmaker", "statut", "jambes", "boost"],
}


def lire_capture(chemin: Path) -> dict:
    """Transcrit une capture de ticket (FDJ, Winamax, Unibet...) en donnees structurees."""
    chemin = chemin.resolve()
    consigne = (
        f"Lis l'image {chemin} avec l'outil Read : c'est un ticket de paris sportifs. "
        "Transcris-le fidelement selon le schema, sans rien deviner. Pour chaque selection : "
        "le match, le sport, le type de pari suivi de la selection (ex. « Double Chance "
        "(Mi-temps) : Nul/Turquie », « Buteur : Lamine Yamal »), la cote, et le resultat "
        "s'il est affiche (coche verte = gagne, croix rouge = perdu, sinon inconnu). "
        "Statut du ticket : gagne, perdu, en_cours, ou inconnu. Le boost combine en "
        "fraction (+2,5 % -> 0.025), 0 s'il n'y en a pas. Si la liste des selections est "
        "repliee ou absente, laisse `jambes` vide."
    )
    commande = [
        config.CLAUDE, "-p", consigne,
        "--model", config.CLAUDE_MODELE,
        "--allowedTools", "Read",
        "--add-dir", str(chemin.parent),
        "--output-format", "json",
        "--json-schema", json.dumps(SCHEMA_CAPTURE),
    ]
    try:
        sortie = subprocess.run(commande, capture_output=True, text=True,
                                timeout=config.CLAUDE_DELAI, cwd=chemin.parent, check=False)
        reponse = json.loads(sortie.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        raise VerificationImpossible(f"Lecture de la capture impossible : {exc}") from exc
    if reponse.get("is_error") or not isinstance(reponse.get("structured_output"), dict):
        raise VerificationImpossible(f"Claude en echec : {str(reponse.get('result'))[:300]}")
    return reponse["structured_output"]

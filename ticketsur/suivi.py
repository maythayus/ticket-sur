"""Suivi des tickets proposes : ce que l'outil annonce, confronte a ce qui arrive."""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from ticketsur.donnees import resultats, saison_de
from ticketsur.marches import gagne
from ticketsur.selection import Ticket
from ticketsur.verification import Verdict


def ouvrir(chemin: Path) -> sqlite3.Connection:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    connexion = sqlite3.connect(chemin)
    connexion.row_factory = sqlite3.Row
    connexion.execute(
        """
        CREATE TABLE IF NOT EXISTS tickets (
            jour TEXT PRIMARY KEY,      -- un ticket par jour : pas de tri a posteriori
            cree_le TEXT NOT NULL,
            cote REAL NOT NULL,
            proba REAL NOT NULL,
            verifie INTEGER NOT NULL,
            statut TEXT NOT NULL DEFAULT 'en_cours',
            selections TEXT NOT NULL
        )
        """
    )
    return connexion


def enregistrer(
    connexion: sqlite3.Connection,
    jour: date,
    ticket: Ticket,
    verdicts: dict[tuple, Verdict] | None,
) -> None:
    selections = [
        {
            "ligue": s.match.ligue,
            "jour": s.match.jour.isoformat(),
            "domicile": s.match.domicile,
            "exterieur": s.match.exterieur,
            "marche": s.marche,
            "libelle": s.libelle,
            "proba": round(s.proba, 4),
            "cote": round(s.cote, 3),
            "verdict": verdicts[s.cle].verdict if verdicts and s.cle in verdicts else None,
        }
        for s in ticket.selections
    ]
    with connexion:
        connexion.execute(
            "INSERT OR REPLACE INTO tickets (jour, cree_le, cote, proba, verifie, statut, selections)"
            " VALUES (?, datetime('now', 'localtime'), ?, ?, ?, 'en_cours', ?)",
            (jour.isoformat(), ticket.cote, ticket.proba, verdicts is not None, json.dumps(selections)),
        )


def regler(connexion: sqlite3.Connection, aujourd_hui: date | None = None) -> int:
    """Regle les tickets dont les scores sont publies. Retourne le nombre regles."""
    aujourd_hui = aujourd_hui or date.today()
    cache: dict[tuple[str, str], dict] = {}
    regles = 0
    for ligne in connexion.execute("SELECT * FROM tickets WHERE statut = 'en_cours'").fetchall():
        issues = []
        for s in json.loads(ligne["selections"]):
            jour = date.fromisoformat(s["jour"])
            if jour >= aujourd_hui:
                issues.append(None)
                continue
            source = (s["ligue"], saison_de(jour))
            if source not in cache:
                cache[source] = resultats(*source)
            score = cache[source].get((s["ligue"], jour, s["domicile"], s["exterieur"]))
            issues.append(None if score is None else gagne(s["marche"], *score))
        if False in issues:
            statut = "perdu"
        elif issues and all(issues):
            statut = "gagne"
        elif date.fromisoformat(ligne["jour"]) < aujourd_hui - timedelta(days=10):
            statut = "annule"  # match reporte ou introuvable : rembourse
        else:
            continue
        with connexion:
            connexion.execute("UPDATE tickets SET statut = ? WHERE jour = ?", (statut, ligne["jour"]))
        regles += 1
    return regles


def statistiques(connexion: sqlite3.Connection) -> dict:
    lignes = connexion.execute(
        "SELECT * FROM tickets WHERE statut IN ('gagne', 'perdu') ORDER BY jour"
    ).fetchall()
    gagnes = [ligne for ligne in lignes if ligne["statut"] == "gagne"]
    en_cours = connexion.execute("SELECT COUNT(*) FROM tickets WHERE statut = 'en_cours'").fetchone()[0]
    return {
        "regles": len(lignes),
        "gagnes": len(gagnes),
        "en_cours": en_cours,
        "taux": len(gagnes) / len(lignes) if lignes else 0.0,
        "taux_prevu": sum(ligne["proba"] for ligne in lignes) / len(lignes) if lignes else 0.0,
        "gain_net": sum(ligne["cote"] for ligne in gagnes) - len(lignes),
        "derniers": [dict(ligne) for ligne in lignes[-10:]],
    }


def marge_erreur(taux: float, effectif: int) -> float:
    """Demi-largeur de l'intervalle a 95 % : un taux mesure sur 20 tickets est flou."""
    return 1.96 * math.sqrt(taux * (1 - taux) / effectif) if effectif else 1.0

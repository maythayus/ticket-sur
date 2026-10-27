"""Reglages centraux, surchargeables par variables d'environnement."""

from __future__ import annotations

import os
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DONNEES = Path(os.getenv("TICKET_DONNEES", str(RACINE / "donnees")))
HISTORIQUE = DONNEES / "historique"
CALIBRATION = DONNEES / "calibration.json"
SUIVI = DONNEES / "suivi.db"

# football-data.co.uk : resultats et cotes moyennes du marche depuis plus de vingt ans,
# et `fixtures.csv` pour les matchs a venir, avec les memes colonnes. Calibrer et predire
# sur la meme source evite de comparer des cotes qui ne se ressemblent pas.
SOURCE = "https://football-data.co.uk"

LIGUES: dict[str, str] = {
    "E0": "Angleterre - Premier League",
    "E1": "Angleterre - Championship",
    "E2": "Angleterre - League One",
    "E3": "Angleterre - League Two",
    "EC": "Angleterre - National League",
    "SC0": "Ecosse - Premiership",
    "SC1": "Ecosse - Championship",
    "SC2": "Ecosse - League One",
    "SC3": "Ecosse - League Two",
    "D1": "Allemagne - Bundesliga",
    "D2": "Allemagne - 2. Bundesliga",
    "I1": "Italie - Serie A",
    "I2": "Italie - Serie B",
    "SP1": "Espagne - Liga",
    "SP2": "Espagne - Liga 2",
    "F1": "France - Ligue 1",
    "F2": "France - Ligue 2",
    "N1": "Pays-Bas - Eredivisie",
    "B1": "Belgique - Pro League",
    "P1": "Portugal - Liga",
    "T1": "Turquie - Super Lig",
    "G1": "Grece - Super League",
}

# Les heures de football-data sont celles du Royaume-Uni.
FUSEAU_SOURCE = "Europe/London"

CLAUDE = os.getenv("TICKET_CLAUDE", "claude")
CLAUDE_MODELE = os.getenv("TICKET_CLAUDE_MODELE", "sonnet")
CLAUDE_DELAI = float(os.getenv("TICKET_CLAUDE_DELAI", "600"))

# Regle de selection par defaut : taux de reussite maximal.
COTE_MIN_TICKET = float(os.getenv("TICKET_COTE_MIN", "1.50"))
COTE_MAX_TICKET = float(os.getenv("TICKET_COTE_MAX", "2.20"))
COTE_MIN_SELECTION = float(os.getenv("TICKET_COTE_MIN_SELECTION", "1.15"))
MAX_SELECTIONS = int(os.getenv("TICKET_MAX_SELECTIONS", "2"))

# Les cotes de football-data sont une moyenne du marche ; un seul bookmaker paie
# d'ordinaire un peu moins. Le backtest applique cette decote a chaque selection.
DECOTE = float(os.getenv("TICKET_DECOTE", "0.97"))

# Garde-fous pour les tickets joues a cote : mise maximale conseillee, et cote minimale
# de la version corrigee proposee par `ticket analyser`.
MISE_MAX = float(os.getenv("TICKET_MISE_MAX", "5"))
COTE_MIN_CORRIGEE = float(os.getenv("TICKET_COTE_MIN_CORRIGEE", "1.30"))

# Part de la mise rendue par un bookmaker sur « les deux equipes marquent », que la
# source ne cote pas : sert a estimer la cote de ce marche (cote = retour / probabilite).
RETOUR_ESTIME = float(os.getenv("TICKET_RETOUR_ESTIME", "0.93"))

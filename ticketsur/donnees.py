"""Telechargement et lecture des fichiers football-data.co.uk."""

from __future__ import annotations

import csv
import io
import logging
import time
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ticketsur import config

log = logging.getLogger(__name__)

# Les noms de colonnes ont change en 2019 (BbAv... -> Avg...) : la moyenne du marche
# d'abord, Bet365 en dernier recours.
COLONNES: dict[str, tuple[str, ...]] = {
    "1": ("AvgH", "BbAvH", "B365H"),
    "N": ("AvgD", "BbAvD", "B365D"),
    "2": ("AvgA", "BbAvA", "B365A"),
    "+2.5": ("Avg>2.5", "BbAv>2.5", "B365>2.5"),
    "-2.5": ("Avg<2.5", "BbAv<2.5", "B365<2.5"),
}


@dataclass
class Match:
    ligue: str
    jour: date
    heure: str
    domicile: str
    exterieur: str
    cotes: dict[str, float]
    buts: tuple[int, int] | None = None

    @property
    def cle(self) -> tuple[str, date, str, str]:
        return (self.ligue, self.jour, self.domicile, self.exterieur)

    def coup_envoi(self) -> datetime | None:
        """Coup d'envoi dans le fuseau de la machine, si l'heure est connue."""
        if not self.heure:
            return None
        try:
            heure = datetime.strptime(self.heure, "%H:%M").time()
        except ValueError:
            return None
        source = datetime.combine(self.jour, heure, ZoneInfo(config.FUSEAU_SOURCE))
        return source.astimezone()


def saison_de(jour: date) -> str:
    """Code de saison football-data : 2627 pour aout 2026 - juin 2027."""
    debut = jour.year if jour.month >= 7 else jour.year - 1
    return f"{debut % 100:02d}{(debut + 1) % 100:02d}"


def saisons_recentes(nombre: int, aujourd_hui: date | None = None) -> list[str]:
    """Les `nombre` dernieres saisons, de la plus ancienne a la courante."""
    aujourd_hui = aujourd_hui or date.today()
    debut = aujourd_hui.year if aujourd_hui.month >= 7 else aujourd_hui.year - 1
    return [saison_de(date(annee, 8, 1)) for annee in range(debut - nombre + 1, debut + 1)]


def _date(texte: str) -> date | None:
    for motif in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(texte.strip(), motif).date()
        except ValueError:
            continue
    return None


def _nombre(ligne: dict[str, str], noms: Iterable[str]) -> float | None:
    for nom in noms:
        try:
            valeur = float(ligne.get(nom) or "")
        except ValueError:
            continue
        if valeur > 1:
            return valeur
    return None


def lire_csv(texte: str) -> list[Match]:
    """Matchs d'un fichier football-data. Les lignes sans cote 1 N 2 sont ignorees."""
    matchs: list[Match] = []
    for ligne in csv.DictReader(io.StringIO(texte)):
        jour = _date(ligne.get("Date") or "")
        domicile = (ligne.get("HomeTeam") or "").strip()
        exterieur = (ligne.get("AwayTeam") or "").strip()
        if not (jour and domicile and exterieur and ligne.get("Div")):
            continue
        cotes = {
            marche: valeur
            for marche, noms in COLONNES.items()
            if (valeur := _nombre(ligne, noms)) is not None
        }
        if not all(issue in cotes for issue in ("1", "N", "2")):
            continue
        buts = None
        if (ligne.get("FTHG") or "").strip().isdigit() and (ligne.get("FTAG") or "").strip().isdigit():
            buts = (int(ligne["FTHG"]), int(ligne["FTAG"]))
        matchs.append(
            Match(
                ligue=ligne["Div"].strip(),
                jour=jour,
                heure=(ligne.get("Time") or "").strip(),
                domicile=domicile,
                exterieur=exterieur,
                cotes=cotes,
                buts=buts,
            )
        )
    return matchs


def _decoder(contenu: bytes) -> str:
    try:
        return contenu.decode("utf-8-sig")
    except UnicodeDecodeError:
        return contenu.decode("latin-1")


def telecharger(url: str, cible: Path, *, age_max: timedelta | None = None) -> Path | None:
    """Telecharge `url` dans `cible`, sauf si le fichier existe et est assez recent.

    `age_max=None` : un fichier deja present n'est jamais retelecharge (saisons closes).
    Retourne None quand la source n'a pas le fichier (ligue absente cette saison-la).
    """
    if cible.is_file():
        age = timedelta(seconds=time.time() - cible.stat().st_mtime)
        if age_max is None or age < age_max:
            return cible
    requete = urllib.request.Request(url, headers={"User-Agent": "ticket-sur/0.1"})
    try:
        with urllib.request.urlopen(requete, timeout=60) as reponse:
            contenu = reponse.read()
    except OSError as exc:
        log.warning("Telechargement impossible : %s (%s)", url, exc)
        return cible if cible.is_file() else None
    if not contenu.strip() or contenu.lstrip().startswith(b"<"):
        return cible if cible.is_file() else None
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_bytes(contenu)
    return cible


def maj_historique(
    nombre_saisons: int, *, afficher: Callable[[str], None] = print, pause: float = 0.3
) -> None:
    """Rapatrie les saisons manquantes ; la saison courante est rafraichie chaque jour."""
    courante = saison_de(date.today())
    for saison in saisons_recentes(nombre_saisons):
        age_max = timedelta(hours=12) if saison == courante else None
        presents = 0
        for ligue in config.LIGUES:
            cible = config.HISTORIQUE / saison / f"{ligue}.csv"
            deja_la = cible.is_file() and age_max is None
            if telecharger(f"{config.SOURCE}/mmz4281/{saison}/{ligue}.csv", cible, age_max=age_max):
                presents += 1
            if not deja_la:
                time.sleep(pause)  # politesse envers un site gratuit
        afficher(f"Saison 20{saison[:2]}-{saison[2:]} : {presents} ligues")


def charger_historique(saisons: Iterable[str] | None = None) -> list[Match]:
    """Tous les matchs joues presents sur le disque, du plus ancien au plus recent."""
    voulues = set(saisons) if saisons is not None else None
    matchs: list[Match] = []
    if not config.HISTORIQUE.is_dir():
        return matchs
    for dossier in sorted(config.HISTORIQUE.iterdir()):
        if voulues is not None and dossier.name not in voulues:
            continue
        for fichier in sorted(dossier.glob("*.csv")):
            matchs.extend(m for m in lire_csv(_decoder(fichier.read_bytes())) if m.buts)
    matchs.sort(key=lambda m: m.jour)
    return matchs


def matchs_a_venir(jour: date) -> list[Match]:
    """Matchs du jour publies dans fixtures.csv (mis a jour plusieurs fois par semaine)."""
    fichier = telecharger(
        f"{config.SOURCE}/fixtures.csv", config.DONNEES / "fixtures.csv", age_max=timedelta(hours=2)
    )
    if not fichier:
        return []
    return [m for m in lire_csv(_decoder(fichier.read_bytes())) if m.jour == jour]


def resultats(ligue: str, saison: str) -> dict[tuple[str, date, str, str], tuple[int, int]]:
    """Scores connus d'une ligue pour une saison, pour regler les tickets."""
    fichier = telecharger(
        f"{config.SOURCE}/mmz4281/{saison}/{ligue}.csv",
        config.HISTORIQUE / saison / f"{ligue}.csv",
        age_max=timedelta(hours=6),
    )
    if not fichier:
        return {}
    return {m.cle: m.buts for m in lire_csv(_decoder(fichier.read_bytes())) if m.buts}

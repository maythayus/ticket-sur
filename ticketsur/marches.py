"""Marches couverts, probabilites justes, cotes et reglement."""

from __future__ import annotations

from ticketsur.buts import attendus, deux_marquent

# 1 N 2 et plus/moins de 2.5 buts sont cotes par la source ; les doubles chances en
# sont deduites, ce qui les rend coherentes avec le 1 N 2 par construction.
MARCHES = ("1", "N", "2", "1N", "N2", "12", "+2.5", "-2.5", "2M", "2M-non")
# Marches que la source ne cote pas : leur cote est estimee (voir selection.candidats).
COTES_ESTIMEES = {"2M", "2M-non"}
_DOUBLES = {"1N": ("1", "N"), "N2": ("N", "2"), "12": ("1", "2")}


def probas_justes(cotes: dict[str, float]) -> dict[str, float]:
    """Probabilites implicites des cotes, marge du bookmaker retiree.

    Retrait proportionnel : le biais connu de cette methode (favoris sous-estimes,
    outsiders surestimes) est corrige ensuite par la calibration sur l'historique.
    """
    inverses = {issue: 1 / cotes[issue] for issue in ("1", "N", "2")}
    total = sum(inverses.values())
    probas = {issue: valeur / total for issue, valeur in inverses.items()}
    for marche, (a, b) in _DOUBLES.items():
        probas[marche] = probas[a] + probas[b]
    if "+2.5" in cotes and "-2.5" in cotes:
        plus, moins = 1 / cotes["+2.5"], 1 / cotes["-2.5"]
        probas["+2.5"] = plus / (plus + moins)
        probas["-2.5"] = moins / (plus + moins)
        dom, ext = attendus(round(probas["1"], 4), round(probas["2"], 4), round(probas["+2.5"], 4))
        probas["2M"] = deux_marquent(dom, ext)
        probas["2M-non"] = 1 - probas["2M"]
    return probas


def cote(cotes: dict[str, float], marche: str) -> float | None:
    """Cote du marche ; celle d'une double chance est estimee depuis le 1 N 2."""
    if marche in _DOUBLES:
        a, b = _DOUBLES[marche]
        return 1 / (1 / cotes[a] + 1 / cotes[b])
    return cotes.get(marche)  # None pour les marches a cote estimee


def gagne(marche: str, buts_dom: int, buts_ext: int) -> bool:
    issue = "1" if buts_dom > buts_ext else "2" if buts_dom < buts_ext else "N"
    if marche in _DOUBLES:
        return issue in _DOUBLES[marche]
    if marche == "+2.5":
        return buts_dom + buts_ext > 2
    if marche == "-2.5":
        return buts_dom + buts_ext < 3
    if marche == "2M":
        return buts_dom > 0 and buts_ext > 0
    if marche == "2M-non":
        return buts_dom == 0 or buts_ext == 0
    return issue == marche


def libelle(marche: str, domicile: str, exterieur: str) -> str:
    return {
        "1": f"Victoire {domicile}",
        "N": "Match nul",
        "2": f"Victoire {exterieur}",
        "1N": f"{domicile} ou nul (1N)",
        "N2": f"{exterieur} ou nul (N2)",
        "12": "Pas de match nul (12)",
        "+2.5": "Plus de 2.5 buts",
        "-2.5": "Moins de 2.5 buts",
        "2M": "Les 2 équipes marquent : oui",
        "2M-non": "Les 2 équipes marquent : non",
    }[marche]

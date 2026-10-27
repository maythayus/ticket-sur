"""Interface en ligne de commande : `ticket maj | jour | backtest | bilan | calibration`."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path

from ticketsur import config
from ticketsur.analyse import NOMS, Billet, depuis_dict, diagnostiquer, issue, version_corrigee
from ticketsur.backtest import Regle, backtest
from ticketsur.buteurs import chercher as chercher_buteurs
from ticketsur.calibration import Calibration, calibrer
from ticketsur.donnees import charger_historique, maj_historique, matchs_a_venir, saison_de
from ticketsur.marches import MARCHES
from ticketsur.selection import Selection, Ticket, candidats, meilleurs_tickets
from ticketsur.suivi import (
    corriger_statut,
    enregistrer,
    journal,
    journaliser,
    marge_erreur,
    ouvrir,
    regler,
    statistiques,
)
from ticketsur.verification import Verdict, VerificationImpossible, lire_capture, verifier

JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre")  # fmt: skip


def _date_longue(jour: date) -> str:
    return f"{JOURS[jour.weekday()]} {jour.day} {MOIS[jour.month - 1]} {jour.year}"


def _regle(args: argparse.Namespace) -> Regle:
    return Regle(args.cote_min, args.cote_max, args.selections, args.cote_min_selection)


def _notifier(titre: str, corps: str, *, urgent: bool = False) -> None:
    if not shutil.which("notify-send"):
        return
    commande = ["notify-send", "--app-name=Ticket sur", titre, corps]
    if urgent:
        commande.insert(1, "--urgency=critical")
    subprocess.run(commande, check=False)


def _calibration() -> Calibration | None:
    if not config.CALIBRATION.is_file():
        print("Pas encore de calibration : lance d'abord `ticket maj`.", file=sys.stderr)
        return None
    return Calibration.charger(config.CALIBRATION)


def choisir(
    selections: list[Selection],
    regle: Regle,
    verificateur: Callable[[list[Selection]], dict[tuple, Verdict]] | None,
) -> tuple[Ticket | None, dict[tuple, Verdict] | None]:
    """Meilleur ticket dont aucune selection n'est ecartee par Claude.

    Claude voit d'un coup les selections des cinq meilleurs tickets, pour avoir des
    remplacants sous la main. Une selection « risque » n'est gardee que faute de mieux.
    """

    def meilleur(exclues: set[tuple], nombre: int = 1) -> list[Ticket]:
        return meilleurs_tickets(
            selections,
            cote_min=regle.cote_min,
            cote_max=regle.cote_max,
            max_selections=regle.max_selections,
            nombre=nombre,
            exclues=exclues,
        )

    if verificateur is None:
        tickets = meilleur(set())
        return (tickets[0] if tickets else None), None

    verdicts: dict[tuple, Verdict] = {}
    for bannis in ({"eviter", "risque"}, {"eviter"}):
        for _ in range(3):
            exclues = {cle for cle, v in verdicts.items() if v.verdict in bannis}
            tickets = meilleur(exclues, nombre=5)
            if not tickets:
                break
            if all(s.cle in verdicts for s in tickets[0].selections):
                return tickets[0], verdicts
            a_verifier: list[Selection] = []
            for ticket in tickets:
                for s in ticket.selections:
                    if s.cle not in verdicts and s not in a_verifier and len(a_verifier) < 8:
                        a_verifier.append(s)
            verdicts.update(verificateur(a_verifier))
    return None, verdicts


def cmd_maj(args: argparse.Namespace) -> int:
    maj_historique(args.saisons)
    matchs = charger_historique()
    calibrer(matchs).sauver(config.CALIBRATION)
    print(f"Calibration : {len(matchs)} matchs -> {config.CALIBRATION}")
    return 0


def cmd_calibration(args: argparse.Namespace) -> int:
    calibration = _calibration()
    if not calibration:
        return 1
    reperes = (0.5, 0.6, 0.7, 0.8, 0.85, 0.9)
    print(f"Calibration sur {calibration.matchs} matchs : probabilité du marché -> taux réel\n")
    print("marché  " + "".join(f"{p:>8.0%}" for p in reperes))
    for marche in MARCHES:
        valeurs = "".join(f"{calibration.proba(marche, p):>8.1%}" for p in reperes)
        print(f"{marche:<8}{valeurs}")
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    matchs = charger_historique()
    if not matchs:
        print("Pas d'historique : lance d'abord `ticket maj`.", file=sys.stderr)
        return 1
    saisons = sorted({saison_de(m.jour) for m in matchs})
    test = saisons[3:]  # trois saisons d'apprentissage au minimum
    print(f"Backtest en avant sur {len(test)} saisons ({test[0]} -> {test[-1]}), "
          f"un ticket par jour de match, {args.selections} sélection(s) max, "
          f"cotes décotées de {1 - config.DECOTE:.0%}\n")
    print(f"{'fourchette':<13}{'tickets':>8}{'réussite':>10}{'annoncé':>9}"
          f"{'gain/ticket':>13}{'pire série':>12}")
    fourchettes = [(1.30, 1.60), (1.50, 2.20), (1.80, 2.60), (2.50, 4.00)]
    if (args.cote_min, args.cote_max) not in fourchettes:
        fourchettes.append((args.cote_min, args.cote_max))
    for cote_min, cote_max in fourchettes:
        regle = Regle(cote_min, cote_max, args.selections, args.cote_min_selection)
        bilan = backtest(matchs, test, regle, config.DECOTE)
        marque = "  <- réglage actuel" if (cote_min, cote_max) == (args.cote_min, args.cote_max) else ""
        print(f"{cote_min:.2f}-{cote_max:.2f}  {bilan.tickets:>8}{bilan.taux:>10.1%}"
              f"{bilan.taux_prevu:>9.1%}{bilan.roi:>+13.1%}{bilan.serie_noire:>12}{marque}")
    print("\nréussite : tickets gagnés / joués.  annoncé : moyenne des probabilités affichées.\n"
          "gain/ticket : bénéfice moyen pour 1 € misé (négatif = perte).\n"
          "pire série : plus longue suite de tickets perdus d'affilée.")
    return 0


def cmd_jour(args: argparse.Namespace) -> int:
    calibration = _calibration()
    if not calibration:
        return 1
    jour, matchs = _matchs_du_jour(args)
    if not matchs:
        message = f"Aucun match couvert à venir le {_date_longue(jour)}."
        print(message)
        if args.notifier:
            _notifier("Ticket sûr : pas de ticket", message)
        return 0

    selections = candidats(matchs, calibration, args.cote_min_selection)
    verificateur = None if args.sans_claude else verifier
    try:
        if verificateur:
            print(f"{len(matchs)} matchs, vérification de l'actualité par Claude…", flush=True)
        ticket, verdicts = choisir(selections, _regle(args), verificateur)
    except VerificationImpossible as exc:
        print(f"Vérification Claude impossible ({exc}) : ticket non vérifié.", file=sys.stderr)
        ticket, verdicts = choisir(selections, _regle(args), None)

    if not ticket:
        message = (f"Aucun ticket entre {args.cote_min:.2f} et {args.cote_max:.2f} "
                   f"parmi {len(matchs)} matchs.")
        print(message)
        if args.notifier:
            _notifier("Ticket sûr : pas de ticket", message)
        return 0

    print(f"\nTicket du {_date_longue(jour)} : cote {ticket.cote:.2f}, "
          f"réussite estimée {ticket.proba:.0%}\n")
    for s in ticket.selections:
        envoi = s.match.coup_envoi()
        print(f"  {envoi.strftime('%H:%M') if envoi else '--:--'}  {s.match.ligue:<4}"
              f"{s.match.domicile} - {s.match.exterieur}")
        cote_txt = f"cote estimée ~{s.cote:.2f}, à vérifier" if s.cote_estimee else f"cote {s.cote:.2f}"
        print(f"         {s.libelle} : {cote_txt}, {s.proba:.0%} "
              f"(modèle {s.proba_marche:.0%})")
        if verdicts and s.cle in verdicts:
            print(f"         Claude [{verdicts[s.cle].verdict}] {verdicts[s.cle].raison}")
    if verdicts is None:
        print("\n  Non vérifié par Claude.")
    print(f"\nCalibré sur {calibration.matchs} matchs. Cote affichée = moyenne du marché : "
          "joue seulement si ton bookmaker paie au moins autant.")

    buteurs = afficher_buteurs(matchs, args.buteurs) if args.buteurs else []
    if not args.essai:
        enregistrer(ouvrir(config.SUIVI), jour, ticket, verdicts)
    if args.notifier:
        corps = "\n".join(f"{s.match.domicile} - {s.match.exterieur} : {s.libelle} ({s.cote:.2f})"
                          for s in ticket.selections)
        if buteurs:
            corps += "\n\nButeurs (cote à exiger) : " + ", ".join(
                f"{b.nom} {b.cote_juste:.2f}" for b in buteurs[:3])
        _notifier(f"Ticket du jour : cote {ticket.cote:.2f}, {ticket.proba:.0%}", corps)
    return 0


def _matchs_du_jour(args: argparse.Namespace) -> tuple[date, list]:
    jour = date.fromisoformat(args.date) if args.date else date.today()
    matchs = matchs_a_venir(jour)
    if jour == date.today():
        limite = datetime.now().astimezone() + timedelta(minutes=15)
        matchs = [m for m in matchs if not (envoi := m.coup_envoi()) or envoi > limite]
    return jour, matchs


def afficher_buteurs(matchs: list, equipes: int) -> list:
    print(f"\nButeurs potentiels (recherche Claude sur les {equipes} attaques les plus fortes)…",
          flush=True)
    try:
        buteurs = chercher_buteurs(matchs, equipes)
    except VerificationImpossible as exc:
        print(f"  {exc}", file=sys.stderr)
        return []
    if not buteurs:
        print("  Aucun buteur trouvé.")
        return []
    print("  Non calibré : estimation à partir des buts attendus et de la saison du joueur.")
    print("  Joue seulement si ton bookmaker paie AU MOINS la cote à exiger.\n")
    for b in buteurs[:8]:
        etat = "titulaire probable" if b.titulaire else "incertain"
        print(f"  {b.nom:<24.24} {b.equipe:<16.16} {b.proba:>4.0%}  cote à exiger {b.cote_juste:>5.2f}"
              f"   ({b.buts} buts, {etat})")
    return buteurs


def cmd_buteurs(args: argparse.Namespace) -> int:
    jour, matchs = _matchs_du_jour(args)
    if not matchs:
        print(f"Aucun match couvert à venir le {_date_longue(jour)}.")
        return 0
    afficher_buteurs(matchs, args.equipes)
    return 0


def cmd_bilan(args: argparse.Namespace) -> int:
    connexion = ouvrir(config.SUIVI)
    regles = regler(connexion)
    stats = statistiques(connexion)
    if regles:
        print(f"{regles} ticket(s) réglé(s) avec les derniers scores.\n")
    if not stats["regles"]:
        print(f"Aucun ticket réglé pour l'instant ({stats['en_cours']} en cours).")
        return 0
    marge = marge_erreur(stats["taux"], stats["regles"])
    print(f"Tickets réglés : {stats['regles']}  (en cours : {stats['en_cours']})")
    print(f"Réussite réelle : {stats['taux']:.0%} ± {marge:.0%}   annoncée : {stats['taux_prevu']:.0%}")
    print(f"Gain net (1 € par ticket, cotes affichées) : {stats['gain_net']:+.2f} €\n")
    for ligne in stats["derniers"]:
        print(f"  {ligne['jour']}  cote {ligne['cote']:.2f}  {ligne['proba']:.0%}  {ligne['statut']}")
    return 0


def _statut(billet: Billet) -> str | None:
    return billet.statut if billet.statut in ("gagne", "perdu") else issue(billet)


def _afficher_analyse(billet: Billet) -> None:
    for j in billet.jambes:
        marque = {"gagne": "✓", "perdu": "✗"}.get(j.resultat or "", " ")
        print(f"  {marque} {j.match:<32.32} {j.pari:<42.42} {j.cote:>5.2f}  ~{j.proba:.0%}")
    mise = f", mise {billet.mise:.2f} €" if billet.mise else ""
    print(f"\nCote {billet.cote_calculee:.2f}{mise} : chance estimée {billet.proba:.1%} "
          f"(1 sur {round(1 / billet.proba) if billet.proba else '∞'}), "
          f"rend en moyenne {billet.esperance:.0%} de la mise.")
    alertes = diagnostiquer(billet)
    if alertes:
        print()
        for alerte in alertes:
            print(f"  {'!!' if alerte.gravite == 'grave' else ' !'} {alerte.message}")
    corrigee = version_corrigee(billet)
    if corrigee:
        print(f"\nVersion corrigée : cote {corrigee.cote_calculee:.2f}, "
              f"chance estimée {corrigee.proba:.0%}")
        for j in corrigee.jambes:
            print(f"    {j.match} : {j.pari} ({j.cote:.2f})")
        if all(j.resultat for j in corrigee.jambes) and _statut(billet):
            verdict = issue(corrigee)
            print(f"    -> aurait été {'GAGNÉE' if verdict == 'gagne' else 'perdue'} "
                  f"(le ticket joué : {'gagné' if _statut(billet) == 'gagne' else 'perdu'})")


def cmd_analyser(args: argparse.Namespace) -> int:
    donnees: list[dict] = []
    if args.cotes:
        donnees.append({"jambes": [{"match": f"Sélection {i + 1}", "pari": "", "cote": c, "type": "resultat"}
                                   for i, c in enumerate(args.cotes)], "mise": args.mise})
    for capture in args.captures:
        print(f"Lecture de {capture} par Claude…", flush=True)
        try:
            lu = lire_capture(Path(capture))
        except VerificationImpossible as exc:
            print(f"  {exc}", file=sys.stderr)
            continue
        if args.mise is not None:
            lu["mise"] = args.mise
        donnees.append(lu)
    if not donnees:
        print("Rien à analyser : donne une capture ou --cotes.", file=sys.stderr)
        return 1
    connexion = ouvrir(config.SUIVI) if args.journal else None
    for brut in donnees:
        billet = depuis_dict(brut)
        print()
        _afficher_analyse(billet)
        if connexion:
            print(f"\nAjouté au journal sous le n° {journaliser(connexion, brut)}.")
    return 0


def cmd_journal(args: argparse.Namespace) -> int:
    connexion = ouvrir(config.SUIVI)
    if args.importer:
        for brut in json.loads(Path(args.importer).read_text(encoding="utf-8")):
            journaliser(connexion, brut)
        print(f"Import de {args.importer} terminé.\n")
    if args.statut:
        numero, statut = args.statut
        if not corriger_statut(connexion, int(numero), statut):
            print(f"Pas de ticket n° {numero} dans le journal.", file=sys.stderr)
            return 1
    entrees = journal(connexion)
    if not entrees:
        print("Journal vide : `ticket analyser capture.jpg --journal` pour y ajouter un ticket.")
        return 0
    if args.detail:
        for numero, brut in entrees:
            if numero == args.detail:
                _afficher_analyse(depuis_dict(brut))
        return 0

    print(f"{'n°':>3}  {'jour':<10} {'sél.':>4} {'cote':>7} {'mise':>6}  {'chance':>7}  statut")
    mises = gains = 0.0
    jambes_connues = jambes_gagnees = 0
    par_type: dict[str, list[int]] = {}
    corrigees = [0.0, 0.0]  # mises et gains de la version corrigee, a mise egale
    par_taille: dict[int, list[int]] = {}
    for numero, brut in entrees:
        billet = depuis_dict(brut)
        statut = _statut(billet)
        cote = billet.cote or billet.cote_calculee
        print(f"{numero:>3}  {(billet.jour or '?'):<10} {len(billet.jambes) or '?':>4} {cote:>7.2f} "
              f"{(billet.mise or 0):>5.0f}€  {billet.proba:>7.1%}  {statut or 'inconnu'}")
        if statut and billet.mise:
            mises += billet.mise
            if statut == "gagne":
                # Le boost s'applique au benefice, pas a la mise rendue.
                gains += billet.mise + billet.mise * (cote - 1) * (1 + billet.boost)
            if billet.jambes:
                compte = par_taille.setdefault(len(billet.jambes), [0, 0])
                compte[0] += 1
                compte[1] += statut == "gagne"
        for j in billet.jambes:
            if j.resultat:
                jambes_connues += 1
                jambes_gagnees += j.resultat == "gagne"
                compte = par_type.setdefault(j.type, [0, 0])
                compte[0] += 1
                compte[1] += j.resultat == "gagne"
        corrigee = version_corrigee(billet)
        if corrigee and billet.mise and all(j.resultat for j in corrigee.jambes):
            corrigees[0] += billet.mise
            if issue(corrigee) == "gagne":
                corrigees[1] += billet.mise * corrigee.cote_calculee

    print(f"\nTickets réglés : misé {mises:.0f} €, repris {gains:.0f} €, net {gains - mises:+.0f} €.")
    for taille, (joues, gagnes) in sorted(par_taille.items()):
        print(f"  à {taille} sélections : {gagnes}/{joues} gagnés")
    if jambes_connues:
        print(f"Sélections au résultat connu : {jambes_gagnees}/{jambes_connues} gagnées "
              f"({jambes_gagnees / jambes_connues:.0%}).")
        for type_, (n, g) in sorted(par_type.items(), key=lambda item: -item[1][0]):
            print(f"  {NOMS.get(type_, type_):<38} {g}/{n}")
    if corrigees[0]:
        print(f"\nAvec les versions corrigées, à mise égale : misé {corrigees[0]:.0f} €, "
              f"repris {corrigees[1]:.0f} €, net {corrigees[1] - corrigees[0]:+.0f} €.")
    return 0


def construire_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ticket",
        description="Tickets de paris courts : calibrés sur l'historique, vérifiés par Claude.",
    )
    parser.add_argument("-v", "--verbeux", action="store_true")
    sous = parser.add_subparsers(dest="commande", required=True)

    maj = sous.add_parser("maj", help="télécharger l'historique et recalibrer")
    maj.add_argument("--saisons", type=int, default=12, help="nombre de saisons (défaut 12)")
    maj.set_defaults(fonction=cmd_maj)

    def options_regle(p: argparse.ArgumentParser) -> None:
        p.add_argument("--cote-min", type=float, default=config.COTE_MIN_TICKET)
        p.add_argument("--cote-max", type=float, default=config.COTE_MAX_TICKET)
        p.add_argument("--selections", type=int, default=config.MAX_SELECTIONS,
                       help="nombre maximal de sélections par ticket")
        p.add_argument("--cote-min-selection", type=float, default=config.COTE_MIN_SELECTION)

    jour = sous.add_parser("jour", help="ticket du jour")
    options_regle(jour)
    jour.add_argument("--date", help="AAAA-MM-JJ (défaut : aujourd'hui)")
    jour.add_argument("--sans-claude", action="store_true", help="sans vérification de l'actualité")
    jour.add_argument("--notifier", action="store_true", help="notification de bureau")
    jour.add_argument("--essai", action="store_true", help="ne pas enregistrer dans le suivi")
    jour.add_argument("--buteurs", type=int, nargs="?", const=4, default=0, metavar="N",
                      help="ajouter les buteurs potentiels des N meilleures attaques (défaut 4)")
    jour.set_defaults(fonction=cmd_jour)

    but = sous.add_parser("buteurs", help="buteurs potentiels du jour et cote à exiger")
    but.add_argument("--date", help="AAAA-MM-JJ (défaut : aujourd'hui)")
    but.add_argument("--equipes", type=int, default=4, help="nombre d'attaques étudiées")
    but.set_defaults(fonction=cmd_buteurs)

    test = sous.add_parser("backtest", help="mesurer la règle sur les saisons passées")
    options_regle(test)
    test.set_defaults(fonction=cmd_backtest)

    analyser = sous.add_parser("analyser", help="analyser un ticket joué (capture ou cotes)")
    analyser.add_argument("captures", nargs="*", help="captures d'écran ou photos du ticket")
    analyser.add_argument("--cotes", type=float, nargs="+", help="saisir les cotes à la main")
    analyser.add_argument("--mise", type=float)
    analyser.add_argument("--journal", action="store_true", help="ajouter au journal")
    analyser.set_defaults(fonction=cmd_analyser)

    jrn = sous.add_parser("journal", help="tes tickets joués : bilan et erreurs récurrentes")
    jrn.add_argument("--importer", help="fichier JSON de tickets à ajouter")
    jrn.add_argument("--statut", nargs=2, metavar=("N", "gagne|perdu"),
                     help="régler un ticket du journal")
    jrn.add_argument("--detail", type=int, metavar="N", help="analyse détaillée d'un ticket")
    jrn.set_defaults(fonction=cmd_journal)

    sous.add_parser("bilan", help="régler les tickets et comparer annoncé / réel").set_defaults(
        fonction=cmd_bilan
    )
    sous.add_parser("calibration", help="afficher la calibration").set_defaults(
        fonction=cmd_calibration
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = construire_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbeux else logging.WARNING,
                        format="%(levelname)s %(message)s")
    return args.fonction(args)

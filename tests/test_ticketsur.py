import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from ticketsur import suivi
from ticketsur.backtest import Regle
from ticketsur.calibration import Calibration, ajuster
from ticketsur.cli import choisir
from ticketsur.donnees import Match, lire_csv, saison_de, saisons_recentes
from ticketsur.marches import cote, gagne, probas_justes
from ticketsur.selection import candidats, meilleurs_tickets
from ticketsur.verification import Verdict


def match(dom="A", ext="B", h=1.5, d=4.0, a=6.0, jour=date(2026, 10, 27), buts=None, ligue="E0"):
    return Match(ligue, jour, "20:00", dom, ext, {"1": h, "N": d, "2": a, "+2.5": 1.8, "-2.5": 2.0}, buts)


class Marches(unittest.TestCase):
    def test_probas_sans_marge(self):
        p = probas_justes(match().cotes)
        self.assertAlmostEqual(p["1"] + p["N"] + p["2"], 1)
        self.assertAlmostEqual(p["+2.5"] + p["-2.5"], 1)
        self.assertAlmostEqual(p["1N"], p["1"] + p["N"])

    def test_cote_double_chance(self):
        self.assertAlmostEqual(cote({"1": 2.0, "N": 2.0, "2": 9.0}, "1N"), 1.0)

    def test_reglement(self):
        self.assertTrue(gagne("1N", 1, 1))
        self.assertFalse(gagne("12", 0, 0))
        self.assertTrue(gagne("+2.5", 2, 1))
        self.assertTrue(gagne("-2.5", 1, 1))
        self.assertTrue(gagne("2", 0, 3))


class Donnees(unittest.TestCase):
    def test_saisons(self):
        self.assertEqual(saison_de(date(2026, 10, 27)), "2627")
        self.assertEqual(saison_de(date(2027, 3, 1)), "2627")
        self.assertEqual(saisons_recentes(2, date(2026, 10, 27)), ["2526", "2627"])

    def test_lecture_ancien_et_nouveau_format(self):
        nouveau = "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,AvgH,AvgD,AvgA,Avg>2.5,Avg<2.5\n" \
                  "E0,25/10/2026,14:00,Man United,Bournemouth,0,3,2.1,3.6,3.2,1.7,2.1\n" \
                  "E0,26/10/2026,14:00,Sans,Cotes,1,1,,,,,\n"
        ancien = "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,BbAvH,BbAvD,BbAvA\n" \
                 "E0,12/08/17,Arsenal,Leicester,4,3,1.5,4.2,6.5\n"
        (m,) = lire_csv(nouveau)
        self.assertEqual((m.buts, m.cotes["+2.5"], m.heure), ((0, 3), 1.7, "14:00"))
        (a,) = lire_csv(ancien)
        self.assertEqual((a.jour, a.cotes["1"]), (date(2017, 8, 12), 1.5))


class Calibrage(unittest.TestCase):
    def test_courbe_croissante_et_reste_fusionne(self):
        paires = [(i / 1000, i % 3 == 0) for i in range(1003)]
        courbe = ajuster(paires, bacs=10)
        taux = [t for _, t, _ in courbe.points]
        self.assertEqual(taux, sorted(taux))
        self.assertGreaterEqual(min(n for _, _, n in courbe.points), 100)

    def test_hors_plage_suit_le_marche(self):
        courbe = ajuster([(0.5, True), (0.5, False), (0.6, True), (0.6, False)] * 100, bacs=2)
        self.assertGreater(courbe(0.9), courbe(0.6))
        self.assertLess(courbe(0.9), 0.95)


class Selection(unittest.TestCase):
    def setUp(self):
        self.calib = Calibration()  # identite : probabilites du marche
        self.matchs = [match("A", "B", 1.3, 5, 9), match("C", "D", 1.25, 5.5, 10), match("E", "F", 2.5, 3.2, 2.8)]

    def test_fourchette_et_un_marche_par_match(self):
        tickets = meilleurs_tickets(candidats(self.matchs, self.calib, 1.15),
                                    cote_min=1.5, cote_max=2.2, max_selections=2, nombre=20)
        self.assertTrue(tickets)
        for t in tickets:
            self.assertTrue(1.5 <= t.cote <= 2.2)
            self.assertEqual(len({s.match.cle for s in t.selections}), len(t.selections))
        self.assertEqual([t.proba for t in tickets], sorted((t.proba for t in tickets), reverse=True))

    def test_claude_ecarte_une_selection(self):
        selections = candidats(self.matchs, self.calib, 1.15)
        regle = Regle(1.5, 2.2, 2, 1.15)
        premier, _ = choisir(selections, regle, None)

        def verificateur(liste):
            return {s.cle: Verdict("eviter" if s.cle == premier.selections[0].cle else "ok", "")
                    for s in liste}

        ticket, verdicts = choisir(selections, regle, verificateur)
        self.assertNotIn(premier.selections[0].cle, [s.cle for s in ticket.selections])
        self.assertTrue(all(verdicts[s.cle].verdict == "ok" for s in ticket.selections))


class Suivi(unittest.TestCase):
    def test_enregistrer_puis_regler(self):
        with tempfile.TemporaryDirectory() as dossier:
            connexion = suivi.ouvrir(Path(dossier) / "suivi.db")
            m = match(jour=date(2026, 10, 20))
            (ticket,) = meilleurs_tickets(candidats([m], Calibration(), 1.15),
                                          cote_min=1.4, cote_max=1.6, max_selections=1)
            suivi.enregistrer(connexion, m.jour, ticket, None)
            score = {m.cle: (2, 0)}
            with mock.patch.object(suivi, "resultats", return_value=score):
                self.assertEqual(suivi.regler(connexion, date(2026, 10, 27)), 1)
            stats = suivi.statistiques(connexion)
            self.assertEqual((stats["regles"], stats["gagnes"]), (1, 1))


if __name__ == "__main__":
    unittest.main()

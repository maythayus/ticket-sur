# Ticket sûr

Un ticket de paris court par jour, choisi pour **passer le plus souvent possible**,
vérifié par Claude Code avant d'être proposé. Inspiré de
[bet-analyst](https://github.com/maythayus/bet-analyst), pensé pour Omarchy.

```
football-data.co.uk ─> calibration sur 86 000 matchs ─> ticket le plus probable
   (cotes moyennes,          (« 80 % » du marché =            dans la fourchette
    résultats, 22 ligues)      combien en vrai ?)               de cote choisie
                                                                     │
          notification Omarchy <─ suivi SQLite <─ Claude Code (claude -p) :
                                                  actualité du jour, peut écarter
```

## Ce que l'outil peut et ne peut pas faire

**Aucun outil ne rend un ticket gagnant à chaque fois.** Les cotes du marché sont déjà
très précises. Ce que l'outil fait :

1. **Calibrer** : sur douze saisons et 22 ligues, il mesure ce que vaut réellement chaque
   probabilité du marché (`ticket calibration`). Les grands favoris gagnent un peu plus
   souvent que leur cote ne l'annonce ; l'outil en tient compte.
2. **Choisir le ticket le plus probable** d'une fourchette de cote, avec une seule
   sélection par match.
3. **Faire vérifier l'actualité par Claude** : blessures, rotation, enjeu. Une sélection
   jugée « à éviter » est remplacée par la suivante.
4. **Mesurer** : chaque ticket est enregistré puis réglé avec le score réel
   (`ticket bilan`), pour vérifier que la réussite annoncée est la réussite obtenue.

### Ce que dit le backtest

Neuf saisons jouées « en avant » : chaque saison est jouée avec une calibration apprise
uniquement sur les saisons précédentes. Un ticket par jour de match, cotes décotées de
3 % (un bookmaker paie un peu moins que la moyenne du marché).

| Cote du ticket | Tickets | Réussite réelle | Annoncée | Gain moyen par ticket | Pire série perdue |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1.30 – 1.60 | 2 155 | **72,8 %** | 73,3 % | −6,6 % | 6 |
| 1.50 – 2.20 (défaut) | 2 187 | **61,9 %** | 63,7 % | −8,8 % | 7 |
| 1.80 – 2.60 | 2 193 | 51,3 % | 52,9 % | −9,7 % | 10 |
| 2.50 – 4.00 | 2 194 | 38,2 % | 37,5 % | −5,7 % | 21 |

À retenir :

- **La cote du ticket fixe son taux de réussite.** C'est le seul vrai levier : un ticket
  à 1.40 passe environ trois fois sur quatre, un ticket à 3.00 une fois sur trois. Une,
  deux ou trois sélections pour une même cote totale : même résultat.
- **Les probabilités annoncées sont fiables**, à un ou deux points près sur plus de
  2 000 tickets. 70 % annoncé ≈ 7 tickets sur 10.
- **Le gain reste négatif** : la marge du bookmaker l'emporte à long terme, quel que
  soit le réglage. Un ticket qui passe souvent rapporte peu quand il passe.
- La vérification Claude n'est pas mesurable sur le passé (l'actualité d'il y a trois
  ans n'est pas archivée) : son effet réel se lira dans `ticket bilan` au fil des
  semaines.

## Installation (Omarchy)

Python 3.11+ et sa bibliothèque standard, rien d'autre. Claude Code doit être installé
et connecté (`claude`), il utilise ton abonnement.

```bash
cd ~/Work/ticket-sur
./installer.sh              # commande `ticket`, historique (~2 min), calibration
./installer.sh --minuteur   # en plus : ticket chaque jour à 10h00 + notification
```

Le minuteur systemd lance chaque matin, dans l'ordre : mise à jour de la saison en
cours, réglage des tickets passés, ticket du jour avec notification. Machine éteinte à
10h00 : il part au démarrage suivant.

```bash
systemctl --user list-timers ticket-sur.timer     # prochaine exécution
journalctl --user -u ticket-sur -n 30             # dernier ticket et son détail
systemctl --user disable --now ticket-sur.timer   # couper le minuteur
```

## Utilisation

```bash
ticket jour                                # ticket du jour, vérifié par Claude
ticket jour --cote-min 1.30 --cote-max 1.60   # plus sûr, rapporte moins
ticket jour --date 2026-10-28 --essai      # un autre jour, sans l'enregistrer
ticket jour --sans-claude                  # sans vérification (instantané)
ticket jour --buteurs                      # avec les buteurs potentiels
ticket buteurs --date 2026-10-28           # buteurs seuls
ticket bilan                               # réussite réelle vs annoncée
ticket backtest                            # rejouer les saisons passées
ticket calibration                         # probabilité du marché -> taux réel
ticket maj                                 # retélécharger, recalibrer
```

**Cote affichée** = moyenne du marché. Joue seulement si ton bookmaker paie au moins
autant. Il est souvent un peu en dessous, et c'est déjà compté dans le backtest.

## « Les 2 équipes marquent » et buteurs potentiels

**Les 2 équipes marquent** fait partie de la sélection automatique. football-data ne cote
pas ce marché : les buts attendus de chaque équipe sont déduits des cotes 1N2 et
plus/moins de 2.5 (`buts.py`), puis la probabilité est calibrée sur l'historique comme
les autres marchés (60 % annoncé → 61 % réel). Sa cote est **estimée** (marge de 7 %
supposée) : le ticket l'indique, vérifie-la chez ton bookmaker.

**Buteurs potentiels** (`ticket buteurs`, ou `ticket jour --buteurs`) : pour les
attaques les plus fortes du jour, Claude cherche les meilleurs buteurs de la saison et
leur statut (titulaire probable ou non). La chance de marquer combine les buts attendus
de l'équipe et la part des buts de l'équipe marqués par le joueur ; le total de l'équipe
vient de football-data, pas du web. L'outil donne la **cote à exiger** : en dessous, le
pari perd de l'argent en moyenne. Pas de calibration possible faute d'historique de
joueurs : ces chiffres sont des estimations, et les buteurs restent hors du ticket.

## Analyser tes propres tickets

`ticket analyser` lit une capture d'écran ou une photo de ticket (FDJ, Winamax, Unibet…)
avec Claude, estime sa vraie chance de passer, signale les erreurs connues et propose
une version corrigée : les une ou deux meilleures sélections du même ticket.

```bash
ticket analyser ~/Images/ticket.jpg            # lecture par Claude
ticket analyser ~/Images/ticket.jpg --journal  # et ajout au journal
ticket analyser --cotes 1.85 1.33 1.26 --mise 2   # saisie à la main
ticket journal                                 # bilan de tes tickets joués
ticket journal --detail 5                      # analyse d'un ticket du journal
ticket journal --statut 1 gagne                # régler un ticket
```

Les erreurs relevées, tirées de vrais tickets :

| Erreur | Pourquoi elle coûte |
| --- | --- |
| 4 à 9 sélections | chaque sélection passe souvent, mais il les faut toutes : le ticket se perd à une sélection près |
| Cote totale de 5 à 200 | 1 chance sur 10 à 1 sur 600 |
| Buteur, mi-temps, combinés maison | marges les plus lourdes, ou beaucoup de hasard |
| Sports et championnats mélangés | rien pour vérifier la sélection |
| Combi boosté | +2,5 à +12 % de gain, contre 10 % de marge perdue par sélection ajoutée |
| Mises de 25 à 40 € | au-dessus de la limite fixée (`TICKET_MISE_MAX`, 5 € par défaut) |

La probabilité d'un ticket joué ailleurs est estimée à partir de sa cote et du type de
pari (le retour aux joueurs est plafonné par la loi à 85 % en moyenne en France) : c'est
un ordre de grandeur, pas la calibration de `ticket jour`.

## Réglages

Variables d'environnement, ou options de `ticket jour` / `ticket backtest` :

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `TICKET_COTE_MIN` / `TICKET_COTE_MAX` | 1.50 / 2.20 | fourchette de cote du ticket |
| `TICKET_MAX_SELECTIONS` | 2 | sélections par ticket au maximum |
| `TICKET_COTE_MIN_SELECTION` | 1.15 | cote minimale d'une sélection |
| `TICKET_DECOTE` | 0.97 | écart supposé entre ton bookmaker et la moyenne (backtest) |
| `TICKET_CLAUDE` | `claude` | chemin de Claude Code |
| `TICKET_CLAUDE_MODELE` | `sonnet` | modèle de la vérification |
| `TICKET_MISE_MAX` | 5 | mise au-delà de laquelle `ticket analyser` alerte |
| `TICKET_DONNEES` | `./donnees` | historique, calibration, suivi, journal |

## Couverture

Les 22 ligues de football-data.co.uk : Angleterre (5 divisions), Écosse (4), Allemagne,
Italie, Espagne, France (2 chacune), Pays-Bas, Belgique, Portugal, Turquie, Grèce.
Pas de coupes ni de compétitions européennes : sans historique de cotes, pas de
calibration honnête.

## Architecture

| Module | Rôle |
| --- | --- |
| `donnees.py` | téléchargement et lecture des CSV, matchs à venir, scores |
| `marches.py` | probabilités sans marge, cotes, règlement des 8 marchés |
| `calibration.py` | régression isotonique par marché |
| `selection.py` | meilleurs tickets d'une fourchette de cote |
| `verification.py` | Claude Code en mode `-p`, recherche web, sortie JSON structurée |
| `backtest.py` | saisons rejouées en avant |
| `suivi.py` | SQLite : un ticket par jour, réglé avec le score réel ; journal des tickets joués |
| `analyse.py` | diagnostic d'un ticket joué, version corrigée |
| `buts.py` | buts attendus déduits des cotes, « les 2 équipes marquent » |
| `buteurs.py` | buteurs potentiels : recherche Claude + buts attendus, cote à exiger |

Tests : `python3 -m unittest discover -s tests`

## Jeu responsable

Le backtest le montre : sur la durée, parier coûte de l'argent, même avec des tickets
bien choisis. Mise uniquement ce que tu acceptes de perdre. Aide gratuite en France :
Joueurs Info Service, 09 74 75 13 13.

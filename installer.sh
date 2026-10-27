#!/usr/bin/env bash
# Installation sous Omarchy : commande `ticket`, historique, et en option le ticket
# quotidien (minuteur systemd utilisateur + notification).
#
#   ./installer.sh             commande ticket + historique + calibration
#   ./installer.sh --minuteur  idem, plus le ticket chaque jour a 10h00
#
# Aucune dependance : Python 3.11+ et sa bibliotheque standard suffisent.

set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
projet="$PWD"

mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/ticket" <<WRAP
#!/usr/bin/env bash
export PYTHONPATH="$projet\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m ticketsur "\$@"
WRAP
chmod +x "$HOME/.local/bin/ticket"
echo "Commande installee : ~/.local/bin/ticket"

"$HOME/.local/bin/ticket" maj

if [[ "${1:-}" == "--minuteur" ]]; then
    # systemd ne voit pas le PATH du terminal (mise) : chemin de claude fige ici.
    claude_bin="$(command -v claude || true)"
    [[ -n "$claude_bin" ]] || echo "Attention : claude introuvable, tickets non verifies."
    unites="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
    mkdir -p "$unites"
    cat > "$unites/ticket-sur.service" <<UNIT
[Unit]
Description=Ticket sur : ticket du jour verifie par Claude
After=network-online.target

[Service]
Type=oneshot
Environment=TICKET_CLAUDE=${claude_bin:-claude}
ExecStartPre=-$HOME/.local/bin/ticket maj --saisons 1
ExecStartPre=-$HOME/.local/bin/ticket bilan
ExecStart=$HOME/.local/bin/ticket jour --notifier --buteurs
UNIT
    cat > "$unites/ticket-sur.timer" <<UNIT
[Unit]
Description=Ticket sur : chaque jour a 10h00

[Timer]
OnCalendar=*-*-* 10:00:00
# Machine eteinte a 10h00 : le ticket part au demarrage suivant.
Persistent=true

[Install]
WantedBy=timers.target
UNIT
    systemctl --user daemon-reload
    systemctl --user enable --now ticket-sur.timer
    echo "Minuteur actif : systemctl --user list-timers ticket-sur.timer"
fi

echo "Pret : ticket jour"

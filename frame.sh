#!/usr/bin/env bash
# Run from your computer (macOS or Linux). Installs/removes the fan cap on a Steam Frame over SSH.
#
#   ./frame.sh status          fan duty, RPM, active cap, hottest sensor
#   ./frame.sh install 85      install the cap service + Quick Access slider, start at 85% (asks for sudo password)
#   ./frame.sh slider          (re)install just the Quick Access slider, no sudo needed
#   ./frame.sh set 70          change the cap (same as moving the slider)
#   ./frame.sh uninstall       back to stock (asks for sudo password)
#   ./frame.sh watch           live fan + temperature readout, Ctrl-C to quit
#   ./frame.sh log             follow the fan service's log
#
# PERCENT is a share of the stock top speed (55% duty, ~5500 rpm): 100 = stock.
# The lowest allowed is 55, which equals the fan's idle speed.
# Set the headset address first: export FRAME=steamos@192.168.1.50  (your Frame's IP)
set -euo pipefail

FRAME="${FRAME:-}"
DEST=/etc/framefan/framefan.py
CAP=/etc/framefan/cap
DROPIN=/etc/systemd/system/deckard-fan-control.service.d/framefan.conf
APPDIR=.local/share/framefan
UNITDIR=.config/systemd/user
here="$(cd "$(dirname "$0")" && pwd)"

push() { scp -q "$here/framefan.py" "$here/framefan_qam.py" "$FRAME:/home/steamos/"; }

# The slider runs as the steamos user, so it needs no sudo. Also retires the old VR dashboard panel.
install_slider() {
  ssh "$FRAME" "systemctl --user disable --now framefan-vr 2>/dev/null; rm -f ~/$UNITDIR/framefan-vr.service ~/$APPDIR/framefan_vr.py
    mkdir -p ~/$APPDIR ~/$UNITDIR && install -m 755 ~/framefan_qam.py ~/$APPDIR/ && cat > ~/$UNITDIR/framefan-qam.service <<'EOF'
[Unit]
Description=Fan cap slider in the Quick Access menu's Performance tab
After=steam.service

[Service]
ExecStart=/usr/bin/python -u %h/$APPDIR/framefan_qam.py
Restart=always
RestartSec=5

[Install]
WantedBy=gamescope-session.service
EOF
    systemctl --user daemon-reload && systemctl --user enable framefan-qam && systemctl --user restart framefan-qam && \
    sleep 2 && echo \"slider service: \$(systemctl --user is-active framefan-qam)\""
}

cmd="${1:-}"; shift || true
if [[ -z "$FRAME" && "$cmd" =~ ^(status|watch|set|slider|install|uninstall|log)$ ]]; then
  echo "Set your headset's address first, e.g.:  export FRAME=steamos@192.168.1.50" >&2
  echo "(find the IP in the Frame's Wi-Fi settings; see README.md)" >&2
  exit 1
fi
case "$cmd" in
  status)
    push
    ssh "$FRAME" "python ~/framefan.py status"
    ;;
  watch)
    push
    ssh -t "$FRAME" "while clear && python ~/framefan.py status; do sleep 1; done"
    ;;
  set)
    pct="${1:?usage: $0 set PERCENT}"
    push
    ssh "$FRAME" "set -o pipefail; python ~/framefan.py check $pct 2>&1 | tail -2 && echo $pct > $CAP"
    ;;
  slider)
    push
    install_slider
    ;;
  install)
    pct="${1:?usage: $0 install PERCENT}"
    push
    # Validate before touching anything; a bad value would otherwise silently run stock.
    ssh "$FRAME" "set -o pipefail; python ~/framefan.py check $pct 2>&1 | tail -2"
    # The service code is root-owned in /etc (survives OS updates, steamos can't edit what root runs).
    # Only the cap value is owned by steamos, so the slider can change it without sudo;
    # the service ignores anything outside 55-100.
    ssh -t "$FRAME" "sudo install -D -m 755 -o root -g root ~/framefan.py $DEST && \
      sudo install -m 644 -o steamos -g steamos /dev/null $CAP && echo $pct > $CAP && \
      sudo mkdir -p $(dirname $DROPIN) && sudo tee $DROPIN >/dev/null <<EOF
# framefan: run Valve's fan controller with a lower top speed. Remove this file to go back to stock.
[Service]
ExecStart=
ExecStart=/usr/bin/python -u $DEST run
ExecStopPost=
ExecStopPost=/usr/bin/python -u $DEST stop
EOF
sudo systemctl daemon-reload && sudo systemctl restart deckard-fan-control && sleep 3 && \
journalctl -u deckard-fan-control -n 2 --no-pager -o cat && python ~/framefan.py status"
    install_slider
    ;;
  uninstall)
    ssh -t "$FRAME" "systemctl --user disable --now framefan-qam framefan-vr 2>/dev/null; \
      rm -rf ~/$UNITDIR/framefan-qam.service ~/$UNITDIR/framefan-vr.service ~/$APPDIR; systemctl --user daemon-reload; \
      sudo rm -rf $DROPIN /etc/framefan /run/framefan && sudo rmdir --ignore-fail-on-non-empty $(dirname $DROPIN); \
      sudo systemctl daemon-reload && sudo systemctl restart deckard-fan-control && echo 'back to stock'"
    ;;
  log)
    ssh -t "$FRAME" "journalctl -fu deckard-fan-control -o cat"
    ;;
  *)
    sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac

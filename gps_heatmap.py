import subprocess
import csv
import os
import signal
import time
import folium
import pandas as pd
import branca.colormap as cm
import sys
from pymavlink import mavutil

# === CONFIGURATION ===
CSV_FILE = "scan_output-01.csv"
INTERFACE = "wlan1mon"
MAVLINK_PORT = "/dev/ttyACM0"  # or /dev/serial0 for UART
BAUD_RATE = 57600
OUTPUT_DURATION = 30  # How long to scan (in seconds)
LOG_FILE = "wifi_gps_log.csv"

if len(sys.argv) > 1: OUTPUT_DURATION = int(sys.argv[1])
# === START MAVLINK CONNECTION ===
print("Connecting to Pixhawk...")
mav = mavutil.mavlink_connection(MAVLINK_PORT, baud=BAUD_RATE)
mav.wait_heartbeat()
print("Pixhawk connected.")

# === FUNCTION: WAIT FOR GPS LOCK ===
def wait_for_gps(mav, min_fix_type=2, min_sats=5, timeout=120):
    start = time.time()
    print(f"Waiting for GPS fix ≥ {min_fix_type} with ≥ {min_sats} satellites...")

    while time.time()- start < timeout:
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

# === FUNCTION: GET GPS ===
def get_gps():
    print("getting position")
    gps = mav.recv_match(type="GPS_RAW_INT", blocking=True, timeout=2)
    if gps: # and gps.fix_type >= 2:
        lat = gps.lat / 1e7
        lon = gps.lon / 1e7
        alt = gps.alt / 1000.0
        print(f"Lat:{lat}\nLon:{lon}\nAlt:{alt}\n")
        return (lat, lon, alt)
    return (None, None, None)

# === CLEAN OLD CSV FILES ===
for file in os.listdir():
    if file.startswith("scan-") and file.endswith(".csv"):
        os.remove(file)

# === CHECK FOR GPS FIX ===
if not wait_for_gps(mav, min_fix_type=2, min_sats=5, timeout=180):
    print("Could not get adequate GPS fix - exiting.")
    exit(1)

# === START AIRODUMP-NG SUBPROCESS ===
print("Starting airodump-ng...")
proc = subprocess.Popen([
    "airodump-ng",
    "--write", "scan",
    "--output-format", "csv",
    INTERFACE
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# === MAIN LOOP ===
start_time = time.time()
print("Collecting data...")

with open(LOG_FILE, "w", newline='') as logfile:
    writer = csv.writer(logfile)
    writer.writerow(["Timestamp", "ESSID", "BSSID", "Signal", "Latitude", "Longitude", "Altitude"])

    while time.time() - start_time < OUTPUT_DURATION:
        time.sleep(1)

        if not os.path.exists(CSV_FILE):
            continue

        try:
            with open(CSV_FILE, newline='') as f:
                reader = csv.reader(f)
                for row in reader:
                    if not row or row[0].strip() in ["BSSID", "Station MAC"]:
                        continue
                    if len(row) < 14:
                        continue
                    essid = row[13].strip()
                    if not essid:
                        continue  # Skip hidden SSID
                    bssid = row[0].strip()
                    power = row[8].strip()

                    lat, lon, alt = get_gps()
                    if lat is not None:
                        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                        writer.writerow([timestamp, essid, bssid, power, lat, lon, alt])
                        print(f"{essid:20} | {power:>4} dBm | {lat:.6f}, {lon:.6f}, {alt:.1f} m")
        except Exception as e:
            print(f"Error parsing CSV: {e}")

# === CLEAN UP ===
print("Stopping airodump-ng...")
proc.send_signal(signal.SIGINT)
proc.wait()
print(f"Logged data to {LOG_FILE}")

df = pd.read_csv("wifi_gps_log.csv")
m = folium.Map(location=[df.Latitude.mean(), df.Longitude.mean()],
               zoom_start=16,
               max_zoom=22)
colormap = cm.linear.RdYlGn_11.scale(df.Signal.min(), df.Signal.max()).to_step(20)
essid_groups = {}

for essid in df.ESSID.unique():
    fg = folium.FeatureGroup(name=essid if essid else '[hidden]')
    essid_groups[essid] = fg
    m.add_child(fg)
for _, row in df.iterrows():
    color=colormap(row.Signal)
    group = essid_groups[row.ESSID]
    folium.CircleMarker(
        location=(row.Latitude, row.Longitude),
        radius=4,
        color=color,
        fill=True,
        popup=f"{row.ESSID or '[hidden]'} ({row.Signal} dBm)"
    ).add_to(group)
folium.LayerControl(collapsed=False).add_to(m)

colormap.caption = 'Signal Strength (dBm)'
colormap.add_to(m)
m.save("wifi_heatmap.html")

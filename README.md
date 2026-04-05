# Dea(u)th Drone – WiFi Penetration Testing Platform

This repository contains the code for the Dea(u)th Drone project, a mobile WiFi reconnaissance and penetration testing platform built on a quadcopter with a Raspberry Pi.

The system performs:
- WiFi access point discovery
- Deauthentication attacks
- WPA/WPA2 handshake capture
- GPS-based signal logging and heatmap generation

This repository includes both the **original implementation** (multi-script workflow) and the **updated unified system** used for field testing.

---

## 📁 Repository Structure

### 🔹 Final Implementation
- `Working/`  
  Contains the **unified Python script** used in the final system.  
  This script integrates scanning, attack execution, and GPS logging.

---

### 🔹 Heatmap Tools
- `generate_heatmap.py`  
  Plots raw GPS data points on a map.

- `grid_heatmap.py`  
  Generates a **grid-based heatmap** by binning and averaging signal strength.

- `Gradient.py`  
  Generates a **linearly interpolated heatmap** from collected data.

---

### 🔹 Original Implementation (Legacy)
- `gps_heatmap.py`  
  Original GPS logging and scanning script.

- `automate-capture.sh`  
- `capture_handshake.sh`  
- `multishake_capture.sh`  

These scripts represent the **earlier design**, where scanning and attack workflows were handled separately.

---

## 🚀 Running the Final Script

The unified script is located in the `Working/` directory.

### Usage

```bash
python3 script_name.py <duration> <skip_gps>
Arguments
<duration>
Time in seconds to run the script
Example: 30 → runs for 30 seconds
-1 → runs indefinitely
<skip_gps>
Whether to skip GPS initialization
0 → use GPS (normal operation)
1 → skip GPS (useful for testing without a GPS fix)

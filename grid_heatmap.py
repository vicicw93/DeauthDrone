import pandas as pd
import folium
import numpy as np
from branca.colormap import linear
import sys
# Load your logged data
if len(sys.argv) > 1:
    df = pd.read_csv(sys.argv[1])
else:
    df = pd.read_csv('wifi_gps_log.csv')


# Grid resolution (degrees — adjust as needed)
lat_step = 0.00005
lon_step = 0.00005

# Create bins
df['lat_bin'] = (df['Latitude'] // lat_step) * lat_step
df['lon_bin'] = (df['Longitude'] // lon_step) * lon_step

# Group by bin and average signal
grid = df.groupby(['lat_bin', 'lon_bin']).Signal.mean().reset_index()

# Set up map and colormap
vmin, vmax = -90, -30
m = folium.Map(location=[df.Latitude.mean(), df.Longitude.mean()], zoom_start=17)
colormap = linear.Spectral_09.scale(vmin, vmax)
colormap.caption = 'Avg Signal Strength (dBm)'
colormap.add_to(m)

# Add each grid cell as a rectangle
for _, row in grid.iterrows():
    sw = [row.lat_bin, row.lon_bin]
    ne = [row.lat_bin + lat_step, row.lon_bin + lon_step]
    color = colormap(row.Signal)
    folium.Rectangle(
        bounds=[sw, ne],
        color=None,
        fill=True,
        fill_color=color,
        fill_opacity=0.6,
        popup=f"{row.Signal:.1f} dBm"
    ).add_to(m)


folium.LayerControl().add_to(m)
m.save("grid_heatmap.html")
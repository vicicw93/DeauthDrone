import tempfile

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from folium import FeatureGroup
from folium.raster_layers import ImageOverlay
from scipy.interpolate import griddata
import folium
from branca.colormap import linear
import branca.colormap as cm
from PIL import Image
import io
from matplotlib.colors import Normalize
from matplotlib import colormaps
from scipy.ndimage import gaussian_filter
import sys
# Load your logged data
if len(sys.argv) > 1:
    df = pd.read_csv(sys.argv[1])
else:
    df = pd.read_csv('wifi_gps_log.csv')

# Extract columns
lats = df['Latitude'].values
for i in lats:
    print(i)
lons = df['Longitude'].values
signals = df['Signal'].values  # usually from -90 to -30 dBm
essids = df['ESSID'].values
print(f"Min signal strength: {min(signals)}\nMax signal strength: {max(signals)}")
# Define map center
center_lat = np.mean(lats)
center_lon = np.mean(lons)

# Define color scale
vmin, vmax = -90, -30
norm = Normalize(vmin=vmin, vmax=vmax)
cmap = colormaps['Spectral']
colormap = linear.Spectral_09.scale(vmin, vmax)
colormap.caption = "Signal Strength (dBm)"

# Create Folium map
m = folium.Map(location=[center_lat, center_lon],
               zoom_start=17,
               #tiles='http://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}',
               #attr='Google Maps',
               #name='Google Maps',
               max_zoom=30)

# Get bounds for all overlays
lat_bounds = [df.Latitude.min(), df.Latitude.max()]
lon_bounds = [df.Longitude.min(), df.Longitude.max()]
image_bounds = [[lat_bounds[0], lon_bounds[0]], [lat_bounds[1], lon_bounds[1]]]

# Group data by ESSID
for essid, group in df.groupby('ESSID'):
    #if len(group) < 5:
    #    continue  # Skip tiny samples for interpolation stability

    # Interpolation grid
    xi = np.linspace(lon_bounds[0], lon_bounds[1], 300)
    yi = np.linspace(lat_bounds[0], lat_bounds[1], 300)
    grid_x, grid_y = np.meshgrid(xi, yi)

    # Interpolate signal values
    grid_z = griddata(
        (group['Longitude'], group['Latitude']),
        group['Signal'],
        (grid_x, grid_y),
        method='linear', #options are linear, nearest or cubic (Don't use cubic)
        rescale=True
    )
    grid_z = gaussian_filter(grid_z, sigma=0.1)
    if grid_z is None:
        continue

    # Clamp to range and map to RGBA
    grid_z = np.clip(grid_z, vmin, vmax)
    rgba = (cmap(norm(grid_z)) * 255).astype(np.uint8)
    img = Image.fromarray(rgba, mode='RGBA')
    img = img.transpose(Image.FLIP_TOP_BOTTOM)

    # Save image to temporary file
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    img.save(tmp.name)

    # Add overlay to the map inside a FeatureGroup
    fg = FeatureGroup(name=essid or "[hidden]", show=False)
    ImageOverlay(
        image=tmp.name,
        bounds=image_bounds,
        opacity=0.6,
        interactive=False,
        cross_origin=False
    ).add_to(fg)
    for _, row in group.iterrows():
        color = colormap(row.Signal)
        folium.CircleMarker(
            location=(row.Latitude, row.Longitude),
            radius=4,
            color=color,
            fill=True,
            popup=f"{row.ESSID or '[hidden]'} ({row.Signal} dBm)"
        ).add_to(fg)
    fg.add_to(m)


# Average signal at each lat/lon pair
avg_df = df.groupby(['Latitude', 'Longitude'], as_index=False)['Signal'].max()

# Interpolation grid
xi = np.linspace(df.Longitude.min(), df.Longitude.max(), 300)
yi = np.linspace(df.Latitude.min(), df.Latitude.max(), 300)
grid_x, grid_y = np.meshgrid(xi, yi)

# Interpolate average signal strength
grid_z = griddata(
    (avg_df['Longitude'], avg_df['Latitude']),
    avg_df['Signal'],
    (grid_x, grid_y),
    method='linear',  # options are linear, nearest or cubic (Don't use cubic)
    rescale=True
)
grid_z = gaussian_filter(grid_z, sigma=0.0)
# Clip and map to color
grid_z = np.clip(grid_z, vmin, vmax)
rgba = (cmap(norm(grid_z)) * 255).astype(np.uint8)
img = Image.fromarray(rgba, mode='RGBA')
img = img.transpose(Image.FLIP_TOP_BOTTOM)

# Save to temp file
tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
img.save(tmp.name)

# Add to map
avg_fg = FeatureGroup(name="Average Signal Heatmap")
image_bounds = [[df.Latitude.min(), df.Longitude.min()],
                [df.Latitude.max(), df.Longitude.max()]]

ImageOverlay(
    image=tmp.name,
    bounds=image_bounds,
    opacity=0.8,
    interactive=False
).add_to(avg_fg)

avg_fg.add_to(m)
# Add controls and legend
folium.LayerControl(collapsed=False).add_to(m)
colormap.add_to(m)
m.save("wifi_per_essid_heatmap2.html")
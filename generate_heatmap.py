import folium
import pandas as pd
import branca.colormap as cm
import sys
# Load your logged data
if len(sys.argv) > 1:
    df = pd.read_csv(sys.argv[1])
else:
    df = pd.read_csv('wifi_gps_log.csv')

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
    color = colormap(row.Signal)
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
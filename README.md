Seismic Risk Monitor

🌍A real-time geospatial analysis tool that monitors global seismic activity and identifies potential risks to populated areas.

🔗 Live DemoView the Interactive Risk Map: https://wvr-spatial.github.io/seismicPython/risk_analysis_output/seismic_risk_map.html

📖 Overview
This tool fetches live data from the USGS Earthquake Feed and Natural Earth Populated Places, performing a spatial join to identify major cities within a 50km radius of significant earthquakes (> Magnitude 4.0).
It generates an interactive Dashboard featuring:
Dark-Mode Map: Styled with high-contrast heatmaps for global visibility.
Risk Zones: Precise impact polygons generated using geodesic buffering.
Antimeridian Fix: Robust handling of the International Date Line to prevent geometry rendering artifacts.
Impact Statistics: Bar charts highlighting the most affected cities by magnitude.

🛠️ InstallationPrerequisites
Python 3.8 or higher, pip (Python package installer)
1. Clone the Repository
2. git clone
3. cd YOUR_REPO_NAME
4. Install Dependencies
This project relies on geospatial libraries. You can install them via pip:pip install geopandas folium plotly shapely requests

Note: On Windows, installing geopandas can sometimes be tricky. If pip fails, it is recommended to use conda or download pre-compiled wheels.

🚀 UsageRun the analysis script directly from your terminal:python seismic_risk_monitor_fixed.py

Output
The script will generate a folder named risk_analysis_output containing:
seismic_risk_map.html: The interactive map (open in any browser).
risk_chart.png: A static bar chart of impacted cities.
risk_chart.html: An interactive version of the chart.

⚙️ How It Works (The "Antimeridian Fix")One common issue in geospatial analysis is the "horizontal line" artifact when projecting geometries that cross the 180th meridian (International Date Line).
This tool includes a custom function handle_antimeridian_buffers() that:
Detects geometries crossing the edge of the Web Mercator projection.
Splits them into MultiPolygons.
Shifts the overflowing segment to the opposite side of the map.
This ensures seamless visualization across the Pacific Ocean.

🤝 Contributing
Feel free to fork this project and submit pull requests. Any improvements to the visualization styling or data sources are welcome!

📝 LicenseThis project is licensed under the MIT License.

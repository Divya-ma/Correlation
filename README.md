# Curve Correlation Explorer

Interactive Streamlit app for trailing correlation analysis on curve/spread data
(Timestamp | col1 | col2 | ... | colN — e.g. CO1, CO1-2, CO2-3, ...).

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open the local URL it prints (usually http://localhost:8501) and upload your
.xlsx file(s) from the sidebar. Works with any file that shares the same column
layout, and with multiple sheets/files.

## What's inside

- **Heatmap** — full correlation matrix (base vs. every column to its right) for a
  chosen trailing window, as of any date you pick with the slider.
- **Time Series** — trailing correlation over the full history for a chosen
  base/target pair, with any window(s) you like overlaid, plus sign-change markers.
- **Year Overlay** — the same pair's correlation plotted by day-of-year, one line
  per calendar year, to compare seasonal shape across years.
- **Summary Table** — mean/std/min/max/last correlation across every valid pair at
  a chosen window, downloadable as CSV.

Toggle **Daily changes vs. Price levels** in the sidebar to switch the correlation
basis. Every chart has a download button (CSV) and a camera icon in the chart
toolbar to save a PNG.

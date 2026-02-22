# SMART-MOVE Mobility Analytics

**Spatial Monitoring & Analysis of Real-Time Traffic Movement**

A QGIS plugin that transforms traffic visualization layers into **spatiotemporal mobility intelligence** for urban transport analysis, regional planning, and digital twin development.

---

## Overview

SMART-MOVE is a spatial mobility analytics framework that extracts, classifies, and analyzes traffic dynamics from visual traffic overlay representations to generate quantitative mobility indicators.

The plugin is designed to support:

- Spatiotemporal congestion monitoring  
- Urban mobility pattern analysis  
- Peak-hour identification  
- Weekly traffic dynamics assessment  
- Visual mobility analytics  
- Evidence-based transport planning  
- Spatial decision support systems  

SMART-MOVE operates using a **visual-proxy mobility analytics approach**, enabling mobility analysis without direct sensor-based traffic data.

---

## System Architecture

SMART-MOVE consists of two core analytical engines.

---

### 1. Traffic Analyzer Engine  
Converts traffic visualization into quantitative spatial data.

**Main functions:**

- Time-indexed traffic tile rendering  
- Hourly traffic raster export  
- Traffic congestion classification  
- Weighted congestion index computation  
- Spatial congestion area statistics  
- Temporal traffic dynamics extraction  

**Output:** spatial analytical datasets

---

### 2. Traffic Summary Visualizer Engine  
Interprets mobility patterns from Analyzer outputs.

**Main functions:**

- Weekly temporal analysis  
- Congestion heatmap generation  
- Peak-hour detection  
- Temporal clustering of traffic conditions  
- Traffic signature analysis  
- Visual analytics for policy interpretation  

**Output:** mobility insights and analytical visualizations

---

## Plugin Outputs

### Traffic Analyzer Outputs
- Hourly traffic rasters (GeoTIFF)
- Traffic class rasters
- Continuous congestion index rasters
- Spatial congestion area statistics
- Hourly mean congestion values
- Weekly traffic summary datasets
- Animated traffic evolution (GIF)
- Analytical CSV datasets

---

### Traffic Summary Visualizer Outputs
- Stacked hourly traffic composition charts
- Mean congestion time series
- Weekly traffic heatmaps
- Peak-hour detection results
- Temporal clustering patterns
- Traffic dominance timeline
- Congestion variability metrics
- Weekday vs weekend comparisons
- Traffic regime patterns

---

## Traffic Classification System

Traffic conditions are classified using HSV color-based interpretation.

| Class | Condition |
|-----|-----|
| 1 | Free Flow |
| 2 | Moderate |
| 3 | Heavy |
| 4 | Severe |

A weighted continuous congestion index is also computed.

---

## Applications in Urban Planning

SMART-MOVE supports:

- Urban mobility digital twin development  
- Traffic policy evaluation  
- Transport corridor analysis  
- Mobility dynamics monitoring  
- Travel behavior studies  
- Temporal accessibility analysis  
- Evidence-based transport planning  
- Spatial decision support systems  

---

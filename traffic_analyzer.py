# -*- coding: utf-8 -*-
"""
QGIS Processing Toolbox Script
Name: Google Traffic Analyzer
Author: Firman Afrianto, Maya Safira
License: GPL-2.0-or-later
"""

import os
import re
import csv
import math

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QImage, QPainter, QColor, QFont, QFontMetrics
from qgis.PyQt.QtCore import QRectF

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterString,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsProcessingParameterEnum,
    QgsCoordinateReferenceSystem,
    QgsProject,
    QgsProcessingUtils,
    QgsRasterLayer,
    QgsRasterFileWriter,
    QgsRasterPipe,
    QgsRasterProjector
)
from qgis import processing

import numpy as np
from osgeo import gdal

try:
    import imageio.v2 as imageio
except Exception:
    imageio = None

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except Exception:
    plt = None


class TrafficAnalyzer(QgsProcessingAlgorithm):

    # Fixed internal base URL (as you requested)
    _FIXED_BASE_URL = (
        "http-header:referer=&type=xyz&url="
        "https://mt0.google.com/vt?"
        "lyrs%3Dh@159000000,traffic%7Cseconds_into_week:{siw}"
        "%26style%3D3%26x%3D{x}%26y%3D{y}%26z%3D{z}"
        "&zmin={zmin}&zmax={zmax}"
    )

    # Params
    ZMIN = "ZMIN"
    ZMAX = "ZMAX"

    BOUNDARY = "BOUNDARY"
    OUTPUT_FOLDER = "OUTPUT_FOLDER"
    FILE_PREFIX = "FILE_PREFIX"
    FILE_SUFFIX = "FILE_SUFFIX"

    DO_CLIP = "DO_CLIP"

    DAY_FILTER = "DAY_FILTER"
    HOUR_MODE = "HOUR_MODE"
    HOUR_START = "HOUR_START"
    HOUR_END = "HOUR_END"
    HOUR_STEP = "HOUR_STEP"
    HOUR_CUSTOM = "HOUR_CUSTOM"
    PRESET = "PRESET"

    ADD_TO_PROJECT = "ADD_TO_PROJECT"
    GROUP_NAME = "GROUP_NAME"

    WRITE_CSV = "WRITE_CSV"
    CSV_NAME = "CSV_NAME"

    DO_CLASSIFY = "DO_CLASSIFY"
    ALPHA_MIN = "ALPHA_MIN"

    # Ignore gray threshold (HSV saturation)
    SAT_MIN = "SAT_MIN"

    # Weights
    W_FREE = "W_FREE"
    W_MOD = "W_MOD"
    W_HEAVY = "W_HEAVY"
    W_SEV = "W_SEV"

    GIF_ENABLE = "GIF_ENABLE"
    GIF_FPS = "GIF_FPS"
    GIF_NAME = "GIF_NAME"

    # NEW: slow down / speed up GIF without changing FPS
    GIF_SECONDS_PER_FRAME = "GIF_SECONDS_PER_FRAME"

    PLOT_ENABLE = "PLOT_ENABLE"
    PLOT_BAR_NAME = "PLOT_BAR_NAME"
    PLOT_LINE_NAME = "PLOT_LINE_NAME"

    MAX_ZOOM_RENDER = "MAX_ZOOM_RENDER"
    MAX_DIM_PX = "MAX_DIM_PX"

    # NEW: organize outputs into subfolders
    ORGANIZE_OUTPUTS = "ORGANIZE_OUTPUTS"
    FOLDER_SCHEME = "FOLDER_SCHEME"

    def tr(self, s):
        return QCoreApplication.translate("TrafficAnalyzer", s)

    def name(self):
        return "traffic_analyzer"

    def displayName(self):
        return self.tr("Traffic Analyzer")

    def group(self):
        return self.tr("SMART-MOVE Mobility Analytics")

    def groupId(self):
        return "transportsimulation"

    def createInstance(self):
        return TrafficAnalyzer()

    def shortHelpString(self):
        return self.tr(
            "<p><b>Created By: Firman Afrianto, Maya Safira</b></p>"
            "<p>This tool exports <b>Google Traffic XYZ tiles</b> using time indexing "
            "based on <b>seconds_into_week</b> into GeoTIFF rasters clipped to the study boundary. "
            "It can optionally generate <b>traffic congestion classes</b>, a <b>weighted congestion index raster</b>, "
            "<b>temporal animation</b>, and <b>hourly statistical summaries</b> to support advanced transport analysis.</p>"

            "<p><b>Legal and Terms of Service safe mode (read carefully)</b></p>"
            "<ul>"
            "<li><b>Interpretive visualization only</b>: outputs are derived from rendered map tiles and transformed into "
            "analysis layers for visual interpretation, modelling, and decision support.</li>"
            "<li><b>Not raw traffic data</b>: results do <b>not</b> represent authoritative measurements (e.g., sensor feeds, "
            "probe data, official speed/travel time records) and must not be treated as ground truth.</li>"
            "<li><b>No redistribution of tiles</b>: do not use this tool to re-publish, mirror, resell, or mass-distribute "
            "map tiles or tile-derived imagery as a substitute for the original service.</li>"
            "<li><b>Use within compliant workflows</b>: intended for internal research, teaching, prototyping, and analytical "
            "visualization workflows. Users remain responsible for compliance with the applicable provider Terms of Service.</li>"
            "<li><b>Attribution</b>: include proper attribution in maps/figures where required by the data provider and your "
            "publication context.</li>"
            "<li><b>Privacy and security</b>: do not attempt to identify individuals or infer personal mobility; outputs are "
            "aggregate visual proxies only.</li>"
            "</ul>"

            "<p><b>Inputs</b></p>"
            "<ul>"
            "<li><b>Boundary polygon</b>: study area used to clip traffic rasters</li>"
            "<li><b>Selected days and hours</b>: manual selection or custom hour ranges</li>"
            "<li><b>Zoom level (Z)</b>: traffic tile spatial resolution</li>"
            "<li><b>Pixel size</b>: optional raster resampling resolution</li>"
            "<li><b>Output options</b>: traffic classification, congestion index, animation, charts</li>"
            "</ul>"

            "<p><b>Time indexing logic</b></p>"
            "<p>Tiles are indexed by position within a weekly cycle:</p>"
            "<pre>seconds_into_week = (day_index * 86400) + (hour * 3600)</pre>"
            "<ul>"
            "<li>Monday = 0</li>"
            "<li>Tuesday = 1</li>"
            "<li>Wednesday = 2</li>"
            "<li>Thursday = 3</li>"
            "<li>Friday = 4</li>"
            "<li>Saturday = 5</li>"
            "<li>Sunday = 6</li>"
            "</ul>"

            "<p><b>What it produces</b></p>"

            "<p><b>A) Traffic raster export</b></p>"
            "<ul>"
            "<li>Hourly traffic GeoTIFF clipped to boundary</li>"
            "<li>Resolution follows native tiles unless a pixel size is specified</li>"
            "</ul>"

            "<p><b>B) Traffic classification and congestion intensity</b></p>"
            "<ul>"
            "<li>Traffic class raster:</li>"
            "<li>1 = Free flow</li>"
            "<li>2 = Moderate</li>"
            "<li>3 = Heavy</li>"
            "<li>4 = Severe</li>"
            "<li>5 = Unknown valid pixel</li>"
            "<li>Weighted congestion index raster (float) computed from class weights</li>"
            "</ul>"

            "<p><b>C) Temporal traffic analytics</b></p>"
            "<ul>"
            "<li>Area per congestion class per hour</li>"
            "<li>Mean congestion index per hour</li>"
            "<li>Hourly statistics table and aggregated weekly summary</li>"
            "</ul>"

            "<p><b>D) Visualization outputs</b></p>"
            "<ul>"
            "<li>Animated GIF with hour labels (optional)</li>"
            "<li>Stacked area chart of class composition (optional)</li>"
            "<li>Mean congestion index line chart (optional)</li>"
            "</ul>"

            "<p><b>Output datasets</b></p>"
            "<ol>"
            "<li><b>Hourly traffic GeoTIFF</b> (visual proxy layer)</li>"
            "<li><b>Traffic class GeoTIFF</b></li>"
            "<li><b>Congestion index GeoTIFF</b></li>"
            "<li><b>Hourly class statistics CSV</b></li>"
            "<li><b>Master summary CSV</b> (area km² and mean index)</li>"
            "<li><b>Animated GIF</b> (optional)</li>"
            "<li><b>Charts PNG</b> (optional)</li>"
            "</ol>"

            "<p><b>Custom hours format</b></p>"
            "<pre>0,1,2,6-10,16-20</pre>"

            "<p><b>Important notes</b></p>"
            "<ul>"
            "<li>Higher zoom levels increase pixel count and memory usage.</li>"
            "<li>Bounding box cropping speeds up processing.</li>"
            "<li>Pixel size = 0 preserves native tile resolution.</li>"
            "<li>Class thresholds and index weights are heuristic and may vary by context.</li>"
            "<li>For scientific reporting, disclose that outputs are <b>tile-derived visual proxies</b> and discuss limitations.</li>"
            "</ul>"

            "<p><b>Dependencies</b></p>"
            "<ul>"
            "<li><b>matplotlib</b> for charts</li>"
            "<li><b>imageio or PIL</b> for animated GIF generation</li>"
            "<li><b>QGIS Processing framework</b></li>"
            "</ul>"
        )

    def initAlgorithm(self, config=None):

        self.addParameter(QgsProcessingParameterNumber(
            self.ZMIN, self.tr("XYZ zmin"),
            type=QgsProcessingParameterNumber.Integer, defaultValue=0, minValue=0, maxValue=24
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.ZMAX, self.tr("XYZ zmax (zoom)"),
            type=QgsProcessingParameterNumber.Integer, defaultValue=16, minValue=0, maxValue=24
        ))

        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        self.addParameter(QgsProcessingParameterEnum(
            self.DAY_FILTER, self.tr("Days to include"),
            options=days, defaultValue=[0, 1, 2, 3, 4, 5, 6], allowMultiple=True
        ))

        presets = [
            "None (use manual filters)",
            "Weekdays only (Mon-Fri), all hours",
            "Weekend only (Sat-Sun), all hours",
            "Weekdays peak AM+PM (06-10 and 16-20)",
            "Weekdays peak AM only (06-10)",
            "Weekdays peak PM only (16-20)"
        ]
        self.addParameter(QgsProcessingParameterEnum(
            self.PRESET, self.tr("Preset"),
            options=presets, defaultValue=0
        ))

        hour_modes = ["All 0-23", "Range", "Custom list"]
        self.addParameter(QgsProcessingParameterEnum(
            self.HOUR_MODE, self.tr("Hour selection mode"),
            options=hour_modes, defaultValue=0
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.HOUR_START, self.tr("Hour start (Range mode)"),
            type=QgsProcessingParameterNumber.Integer, defaultValue=0, minValue=0, maxValue=23
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.HOUR_END, self.tr("Hour end inclusive (Range mode)"),
            type=QgsProcessingParameterNumber.Integer, defaultValue=23, minValue=0, maxValue=23
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.HOUR_STEP, self.tr("Hour step (Range mode)"),
            type=QgsProcessingParameterNumber.Integer, defaultValue=1, minValue=1, maxValue=24
        ))
        self.addParameter(QgsProcessingParameterString(
            self.HOUR_CUSTOM, self.tr("Custom hours (Custom list mode), example 0,1,2,6-10,16-20"),
            defaultValue="", optional=True
        ))

        self.addParameter(QgsProcessingParameterFeatureSource(
            self.BOUNDARY, self.tr("Boundary polygon (mask and extent)"),
            [QgsProcessing.TypeVectorPolygon]
        ))

        self.addParameter(QgsProcessingParameterFolderDestination(
            self.OUTPUT_FOLDER, self.tr("Output folder")
        ))

        # NEW: organize outputs
        self.addParameter(QgsProcessingParameterBoolean(
            self.ORGANIZE_OUTPUTS, self.tr("Organize outputs into subfolders (recommended)"),
            defaultValue=True
        ))
        schemes = [
            "By day (Monday..Sunday) + common folders",
            "By day_index (0..6) + common folders",
            "Flat (no subfolders)"
        ]
        self.addParameter(QgsProcessingParameterEnum(
            self.FOLDER_SCHEME, self.tr("Folder scheme"),
            options=schemes, defaultValue=0
        ))

        self.addParameter(QgsProcessingParameterString(
            self.FILE_PREFIX, self.tr("Output filename prefix"), defaultValue="xyz_"
        ))
        self.addParameter(QgsProcessingParameterString(
            self.FILE_SUFFIX, self.tr("Output filename suffix"), defaultValue="", optional=True
        ))

        self.addParameter(QgsProcessingParameterBoolean(
            self.DO_CLIP, self.tr("Clip by boundary polygon (cutline mask)"),
            defaultValue=True
        ))

        self.addParameter(QgsProcessingParameterBoolean(
            self.WRITE_CSV, self.tr("Write metadata CSV"),
            defaultValue=True
        ))
        self.addParameter(QgsProcessingParameterString(
            self.CSV_NAME, self.tr("CSV filename"),
            defaultValue="xyz_weekly_index.csv"
        ))

        self.addParameter(QgsProcessingParameterBoolean(
            self.ADD_TO_PROJECT, self.tr("Add outputs to current QGIS project"),
            defaultValue=True
        ))
        self.addParameter(QgsProcessingParameterString(
            self.GROUP_NAME, self.tr("Project group name"),
            defaultValue="Traffic XYZ Weekly"
        ))

        self.addParameter(QgsProcessingParameterBoolean(
            self.DO_CLASSIFY, self.tr("Create traffic classes + congestion index + summary tables"),
            defaultValue=True
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.ALPHA_MIN, self.tr("Minimum alpha to treat as valid pixel (0-255)"),
            type=QgsProcessingParameterNumber.Integer, defaultValue=10, minValue=0, maxValue=255
        ))

        self.addParameter(QgsProcessingParameterNumber(
            self.SAT_MIN, self.tr("Minimum HSV saturation to treat as traffic overlay (ignore gray)"),
            type=QgsProcessingParameterNumber.Double, defaultValue=0.25, minValue=0.0, maxValue=1.0
        ))

        self.addParameter(QgsProcessingParameterNumber(
            self.W_FREE, self.tr("Weight for Free flow class"),
            type=QgsProcessingParameterNumber.Double, defaultValue=0.25, minValue=0.0, maxValue=1.0
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.W_MOD, self.tr("Weight for Moderate class"),
            type=QgsProcessingParameterNumber.Double, defaultValue=0.50, minValue=0.0, maxValue=1.0
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.W_HEAVY, self.tr("Weight for Heavy class"),
            type=QgsProcessingParameterNumber.Double, defaultValue=0.75, minValue=0.0, maxValue=1.0
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.W_SEV, self.tr("Weight for Severe class"),
            type=QgsProcessingParameterNumber.Double, defaultValue=1.00, minValue=0.0, maxValue=1.0
        ))

        self.addParameter(QgsProcessingParameterBoolean(
            self.GIF_ENABLE, self.tr("Create animated GIF (labeled frames)"),
            defaultValue=True
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.GIF_FPS, self.tr("GIF frames per second (playback speed)"),
            type=QgsProcessingParameterNumber.Double, defaultValue=1.0, minValue=0.01, maxValue=60.0
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.GIF_SECONDS_PER_FRAME, self.tr("GIF seconds per frame (override FPS, 0 = auto from FPS)"),
            type=QgsProcessingParameterNumber.Double, defaultValue=0.0, minValue=0.0, maxValue=30.0
        ))
        self.addParameter(QgsProcessingParameterString(
            self.GIF_NAME, self.tr("GIF filename"),
            defaultValue="traffic_animation.gif", optional=True
        ))

        self.addParameter(QgsProcessingParameterBoolean(
            self.PLOT_ENABLE, self.tr("Create hourly charts PNG (requires matplotlib)"),
            defaultValue=True
        ))
        self.addParameter(QgsProcessingParameterString(
            self.PLOT_BAR_NAME, self.tr("Hourly stacked bar PNG filename"),
            defaultValue="hourly_traffic_area_stacked.png", optional=True
        ))
        self.addParameter(QgsProcessingParameterString(
            self.PLOT_LINE_NAME, self.tr("Hourly mean congestion line PNG filename"),
            defaultValue="hourly_mean_congestion_index.png", optional=True
        ))

        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_ZOOM_RENDER, self.tr("Max zoom allowed for rendering (safety)"),
            type=QgsProcessingParameterNumber.Integer, defaultValue=18, minValue=0, maxValue=24
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_DIM_PX, self.tr("Max output dimension (px) for rendering (safety)"),
            type=QgsProcessingParameterNumber.Integer, defaultValue=12000, minValue=512, maxValue=60000
        ))

    # -------------
    # Helpers
    # -------------

    def _safe_name(self, s):
        s2 = (s or "").strip().replace(":", "_")
        s2 = re.sub(r"\s+", "_", s2)
        s2 = re.sub(r"[^0-9A-Za-z_\-\.]", "_", s2)
        s2 = re.sub(r"_+", "_", s2)
        return s2

    def _ensure_dir(self, p):
        if p and (not os.path.isdir(p)):
            os.makedirs(p, exist_ok=True)
        return p

    def _day_folder_name(self, dname, dindex, scheme):
        if int(scheme) == 0:
            return self._safe_name(dname)
        if int(scheme) == 1:
            return f"day_{int(dindex)}"
        return ""

    def _prepare_output_structure(self, out_folder, scheme, feedback):
        scheme = int(scheme)
        if scheme == 2:
            tmp_dir = self._ensure_dir(os.path.join(out_folder, "__tmp"))
            return {
                "base": out_folder,
                "scheme": scheme,
                "tmp": tmp_dir,
                "meta": out_folder,
                "rasters": out_folder,
                "classes": out_folder,
                "cindex": out_folder,
                "tables": out_folder,
                "frames": out_folder,
                "products": out_folder
            }

        dirs = {
            "base": out_folder,
            "scheme": scheme,
            "meta": self._ensure_dir(os.path.join(out_folder, "00_inputs_meta")),
            "rasters": self._ensure_dir(os.path.join(out_folder, "01_rasters")),
            "classes": self._ensure_dir(os.path.join(out_folder, "02_classes")),
            "cindex": self._ensure_dir(os.path.join(out_folder, "03_cindex")),
            "tables": self._ensure_dir(os.path.join(out_folder, "04_tables")),
            "frames": self._ensure_dir(os.path.join(out_folder, "05_frames_png")),
            "products": self._ensure_dir(os.path.join(out_folder, "06_products")),
            "tmp": self._ensure_dir(os.path.join(out_folder, "__tmp"))
        }
        feedback.pushInfo("Output folders created under: " + out_folder)
        return dirs

    def _subdir_for_day(self, root_dir, dname, dindex, scheme):
        scheme = int(scheme)
        if scheme == 2:
            return root_dir
        day_folder = self._day_folder_name(dname, dindex, scheme)
        p = os.path.join(root_dir, day_folder)
        self._ensure_dir(p)
        return p

    def _parse_custom_hours(self, text):
        if not text or not text.strip():
            return []
        items = re.split(r"[,\s;]+", text.strip())
        hours = set()
        for it in items:
            if not it:
                continue
            m = re.match(r"^([01]?\d|2[0-3])\s*-\s*([01]?\d|2[0-3])$", it)
            if m:
                a = int(m.group(1))
                b = int(m.group(2))
                lo, hi = (a, b) if a <= b else (b, a)
                for h in range(lo, hi + 1):
                    hours.add(h)
                continue
            m2 = re.match(r"^([01]?\d|2[0-3])$", it)
            if m2:
                hours.add(int(m2.group(1)))
        return sorted([h for h in hours if 0 <= h <= 23])

    def _resolve_filters(self, parameters, context):
        day_indices = self.parameterAsEnums(parameters, self.DAY_FILTER, context)

        preset = self.parameterAsInt(parameters, self.PRESET, context)
        hour_mode = self.parameterAsInt(parameters, self.HOUR_MODE, context)

        if preset == 1:
            return [0, 1, 2, 3, 4], list(range(24))
        if preset == 2:
            return [5, 6], list(range(24))
        if preset == 3:
            return [0, 1, 2, 3, 4], sorted(set(list(range(6, 11)) + list(range(16, 21))))
        if preset == 4:
            return [0, 1, 2, 3, 4], list(range(6, 11))
        if preset == 5:
            return [0, 1, 2, 3, 4], list(range(16, 21))

        if hour_mode == 0:
            return day_indices, list(range(24))

        if hour_mode == 1:
            hs = self.parameterAsInt(parameters, self.HOUR_START, context)
            he = self.parameterAsInt(parameters, self.HOUR_END, context)
            step = max(1, self.parameterAsInt(parameters, self.HOUR_STEP, context))
            lo, hi = (hs, he) if hs <= he else (he, hs)
            hours = [h for h in range(lo, hi + 1, step) if 0 <= h <= 23]
            return day_indices, hours

        text = self.parameterAsString(parameters, self.HOUR_CUSTOM, context)
        hours = self._parse_custom_hours(text)
        return day_indices, hours

    def _xyz_uri(self, base_url_template, siw, zmin, zmax):
        url = base_url_template.replace("{siw}", str(int(siw)))
        url = url.replace("{zmin}", str(int(zmin))).replace("{zmax}", str(int(zmax)))
        return url

    def _export_xyz_to_tif(self, rl, out_path, extent_3857, zoom, max_dim_px, feedback):
        if extent_3857 is None or extent_3857.isEmpty():
            raise QgsProcessingException("Export extent is empty.")

        z = int(zoom)
        mpp = 156543.03392804097 / (2 ** z)

        width = max(1, int(math.ceil(extent_3857.width() / mpp)))
        height = max(1, int(math.ceil(extent_3857.height() / mpp)))

        if width > int(max_dim_px) or height > int(max_dim_px):
            raise QgsProcessingException(
                f"Render size too large: {width}x{height}px. Reduce ZMAX or boundary size, or increase MAX_DIM_PX."
            )

        pipe = QgsRasterPipe()
        if not pipe.set(rl.dataProvider().clone()):
            raise QgsProcessingException("Failed to create raster pipe from XYZ provider.")

        projector = QgsRasterProjector()
        projector.setCrs(rl.crs(), QgsCoordinateReferenceSystem("EPSG:3857"),
                         QgsProject.instance().transformContext())
        pipe.insert(2, projector)

        fw = QgsRasterFileWriter(out_path)
        fw.setOutputFormat("GTiff")

        res = fw.writeRaster(
            pipe, width, height, extent_3857,
            QgsCoordinateReferenceSystem("EPSG:3857"),
            QgsProject.instance().transformContext()
        )
        if res != QgsRasterFileWriter.NoError:
            raise QgsProcessingException(f"Raster export failed with code: {res}")

        feedback.pushInfo(f"Rendered XYZ to: {out_path} (zoom={z}, mpp={mpp}, size={width}x{height})")

    def _prepare_boundary_3857(self, boundary_layer, context, feedback):
        feedback.pushInfo("Preparing boundary in EPSG:3857 (reproject + fix + dissolve)...")

        res1 = processing.run("native:reprojectlayer", {
            "INPUT": boundary_layer,
            "TARGET_CRS": QgsCoordinateReferenceSystem("EPSG:3857"),
            "OUTPUT": "memory:"
        }, context=context, feedback=feedback)
        lyr1 = res1["OUTPUT"]

        res2 = processing.run("native:fixgeometries", {
            "INPUT": lyr1,
            "OUTPUT": "memory:"
        }, context=context, feedback=feedback)
        lyr2 = res2["OUTPUT"]

        res3 = processing.run("native:dissolve", {
            "INPUT": lyr2,
            "FIELD": [],
            "OUTPUT": "memory:"
        }, context=context, feedback=feedback)
        lyr3 = res3["OUTPUT"]

        return lyr3

    # ---------- HSV utilities ----------

    def _rgb_to_hsv(self, r, g, b):
        rf = r.astype(np.float32) / 255.0
        gf = g.astype(np.float32) / 255.0
        bf = b.astype(np.float32) / 255.0

        cmax = np.maximum(rf, np.maximum(gf, bf))
        cmin = np.minimum(rf, np.minimum(gf, bf))
        delta = cmax - cmin

        h = np.zeros_like(cmax, dtype=np.float32)

        mask = delta > 1e-6
        m = mask & (cmax == rf)
        h[m] = (60.0 * (((gf[m] - bf[m]) / delta[m]) % 6.0))
        m = mask & (cmax == gf)
        h[m] = (60.0 * (((bf[m] - rf[m]) / delta[m]) + 2.0))
        m = mask & (cmax == bf)
        h[m] = (60.0 * (((rf[m] - gf[m]) / delta[m]) + 4.0))

        s = np.zeros_like(cmax, dtype=np.float32)
        s[cmax > 1e-6] = delta[cmax > 1e-6] / cmax[cmax > 1e-6]

        v = cmax
        return h, s, v

    def _classify_hsv_traffic(self, in_tif, out_class_tif, out_index_tif, out_csv,
                              alpha_min, sat_min, w_free, w_mod, w_heavy, w_sev, feedback):
        ds = gdal.Open(in_tif, gdal.GA_ReadOnly)
        if ds is None:
            raise QgsProcessingException("Cannot open raster: " + in_tif)
        if ds.RasterCount < 3:
            raise QgsProcessingException("Raster must have RGB bands.")

        r = ds.GetRasterBand(1).ReadAsArray()
        g = ds.GetRasterBand(2).ReadAsArray()
        b = ds.GetRasterBand(3).ReadAsArray()

        if ds.RasterCount >= 4:
            a = ds.GetRasterBand(4).ReadAsArray()
        else:
            a = np.full(r.shape, 255, dtype=np.uint8)

        valid_alpha = a >= int(alpha_min)
        h, s, v = self._rgb_to_hsv(r, g, b)

        traffic_mask = valid_alpha & (s >= float(sat_min)) & (v >= 0.10)

        m_green = traffic_mask & (h >= 75.0) & (h <= 165.0)
        m_orange = traffic_mask & (h >= 20.0) & (h < 75.0)
        m_red = traffic_mask & ((h < 20.0) | (h >= 340.0))

        m_severe = m_red & (v < 0.55)
        m_heavy = m_red & (~m_severe)

        cls = np.zeros(r.shape, dtype=np.uint8)
        cls[m_green] = 1
        cls[m_orange] = 2
        cls[m_heavy] = 3
        cls[m_severe] = 4

        idx = np.full(r.shape, -9999.0, dtype=np.float32)
        idx[m_green] = float(w_free)
        idx[m_orange] = float(w_mod)
        idx[m_heavy] = float(w_heavy)
        idx[m_severe] = float(w_sev)

        driver = gdal.GetDriverByName("GTiff")

        out_ds = driver.Create(out_class_tif, ds.RasterXSize, ds.RasterYSize, 1, gdal.GDT_Byte,
                               options=["COMPRESS=LZW"])
        out_ds.SetGeoTransform(ds.GetGeoTransform())
        out_ds.SetProjection(ds.GetProjection())
        out_ds.GetRasterBand(1).WriteArray(cls)
        out_ds.GetRasterBand(1).SetNoDataValue(0)
        out_ds.FlushCache()
        out_ds = None

        out_ds2 = driver.Create(out_index_tif, ds.RasterXSize, ds.RasterYSize, 1, gdal.GDT_Float32,
                                options=["COMPRESS=LZW"])
        out_ds2.SetGeoTransform(ds.GetGeoTransform())
        out_ds2.SetProjection(ds.GetProjection())
        b1 = out_ds2.GetRasterBand(1)
        b1.WriteArray(idx)
        b1.SetNoDataValue(-9999.0)
        out_ds2.FlushCache()
        out_ds2 = None

        gt = ds.GetGeoTransform()
        px_area = abs(gt[1] * gt[5])
        ds = None

        def count(c):
            return int((cls == c).sum())

        rows = [
            ("1", "Free (Green)", count(1)),
            ("2", "Moderate (Orange)", count(2)),
            ("3", "Heavy (Red)", count(3)),
            ("4", "Severe (Dark Red)", count(4)),
        ]

        with open(out_csv, "w", encoding="utf-8", newline="") as f:
            f.write("class_id,class_name,pixel_count,area_m2,area_km2\n")
            for cid, name, n in rows:
                area_m2 = float(n) * px_area
                area_km2 = area_m2 / 1e6
                f.write(f"{cid},{name},{n},{area_m2},{area_km2}\n")

        summary = {cid: {"name": name, "px": n, "km2": (float(n) * px_area / 1e6)} for cid, name, n in rows}

        valid_idx = idx[idx > -9000]
        mean_idx = float(valid_idx.mean()) if valid_idx.size > 0 else 0.0

        feedback.pushInfo("Class raster: " + out_class_tif)
        feedback.pushInfo("Index raster: " + out_index_tif)
        feedback.pushInfo("Class table: " + out_csv)
        return summary, mean_idx

    def _tif_to_png_with_label(self, in_tif, out_png, label_text, context, feedback):
        processing.run("gdal:translate", {
            "INPUT": in_tif,
            "TARGET_CRS": None,
            "NODATA": None,
            "COPY_SUBDATASETS": False,
            "OPTIONS": [],
            "EXTRA": "",
            "DATA_TYPE": 0,
            "OUTPUT": out_png
        }, context=context, feedback=feedback)

        img = QImage(out_png)
        if img.isNull():
            feedback.pushWarning("Failed to open PNG for labeling: " + out_png)
            return

        w_img = img.width()
        font_px = int(round(w_img * 0.018))
        font_px = max(16, min(64, font_px))

        margin = int(round(w_img * 0.012))
        margin = max(10, min(40, margin))

        pad = int(round(font_px * 0.55))
        pad = max(8, min(28, pad))

        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing, True)

        font = QFont("Arial")
        font.setPixelSize(font_px)
        painter.setFont(font)

        metrics = QFontMetrics(font)
        text_rect = metrics.boundingRect(label_text)

        box_w = text_rect.width() + 2 * pad
        box_h = text_rect.height() + 2 * pad

        x0 = margin
        y0 = margin

        box_w = min(box_w, w_img - 2 * margin)
        box_h = min(box_h, img.height() - 2 * margin)

        painter.setPen(QColor(255, 255, 255, 255))
        painter.setBrush(QColor(0, 0, 0, 140))

        r = max(6, int(round(font_px * 0.35)))
        painter.drawRoundedRect(QRectF(x0, y0, box_w, box_h), r, r)

        painter.setPen(QColor(255, 255, 255, 255))

        text_x = x0 + pad
        text_y = y0 + pad + metrics.ascent()
        painter.drawText(text_x, text_y, label_text)

        painter.end()
        img.save(out_png)

    def _write_gif(self, png_paths, gif_path, fps, seconds_per_frame, feedback):
        if imageio is None:
            feedback.pushWarning("imageio not available, skipping GIF.")
            return False

        frames = [imageio.imread(p) for p in png_paths if os.path.exists(p)]
        if not frames:
            feedback.pushWarning("No frames found for GIF.")
            return False

        spf = float(seconds_per_frame or 0.0)
        if spf > 0.0:
            duration = spf
        else:
            fps = float(fps)
            duration = 1.0 / max(0.001, fps)

        imageio.mimsave(gif_path, frames, duration=duration)
        feedback.pushInfo("GIF written: " + gif_path + f" (duration per frame = {duration}s)")
        return True

    def _make_hourly_plots(self, master_csv, out_folder, bar_name, line_name, feedback):
        if (not master_csv) or (not os.path.exists(master_csv)):
            feedback.pushWarning("Master CSV not found, skipping plots.")
            return {"BAR_PNG": "", "LINE_PNG": ""}

        if plt is None:
            feedback.pushWarning("matplotlib not available, skipping plots.")
            return {"BAR_PNG": "", "LINE_PNG": ""}

        rows = []
        with open(master_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                try:
                    hour = int(float(r.get("hour", "0")))
                except Exception:
                    continue

                def fnum(k):
                    try:
                        return float(r.get(k, "0") or 0.0)
                    except Exception:
                        return 0.0

                rows.append({
                    "hour": hour,
                    "free_km2": fnum("free_km2"),
                    "moderate_km2": fnum("moderate_km2"),
                    "heavy_km2": fnum("heavy_km2"),
                    "severe_km2": fnum("severe_km2"),
                    "mean_cindex": fnum("mean_cindex"),
                })

        if not rows:
            feedback.pushWarning("Master CSV has no rows, skipping plots.")
            return {"BAR_PNG": "", "LINE_PNG": ""}

        by_hour = {}
        for r in rows:
            h = r["hour"]
            if h not in by_hour:
                by_hour[h] = {"n": 0, "free_km2": 0.0, "moderate_km2": 0.0,
                              "heavy_km2": 0.0, "severe_km2": 0.0, "mean_cindex": 0.0}
            by_hour[h]["n"] += 1
            by_hour[h]["free_km2"] += r["free_km2"]
            by_hour[h]["moderate_km2"] += r["moderate_km2"]
            by_hour[h]["heavy_km2"] += r["heavy_km2"]
            by_hour[h]["severe_km2"] += r["severe_km2"]
            by_hour[h]["mean_cindex"] += r["mean_cindex"]

        hours = sorted(by_hour.keys())
        n = [max(1, by_hour[h]["n"]) for h in hours]

        free = [by_hour[h]["free_km2"] / n[i] for i, h in enumerate(hours)]
        mod = [by_hour[h]["moderate_km2"] / n[i] for i, h in enumerate(hours)]
        heavy = [by_hour[h]["heavy_km2"] / n[i] for i, h in enumerate(hours)]
        sev = [by_hour[h]["severe_km2"] / n[i] for i, h in enumerate(hours)]
        cidx = [by_hour[h]["mean_cindex"] / n[i] for i, h in enumerate(hours)]

        bar_png = os.path.join(out_folder, self._safe_name(bar_name))
        line_png = os.path.join(out_folder, self._safe_name(line_name))

        # Match legend colors (Google-like)
        C_FREE  = "#34A853"  # Green
        C_MOD   = "#FBBC05"  # Orange
        C_HEAVY = "#EA4335"  # Red
        C_SEV   = "#8B0000"  # Dark Red

        try:
            plt.figure(figsize=(12, 5))
            x = np.arange(len(hours))
            b1 = np.array(free)
            b2 = np.array(mod)
            b3 = np.array(heavy)
            b4 = np.array(sev)

            plt.bar(x, b1, label="Free (Green)", color=C_FREE)
            plt.bar(x, b2, bottom=b1, label="Moderate (Orange)", color=C_MOD)
            plt.bar(x, b3, bottom=b1 + b2, label="Heavy (Red)", color=C_HEAVY)
            plt.bar(x, b4, bottom=b1 + b2 + b3, label="Severe (Dark Red)", color=C_SEV)

            plt.xticks(x, [str(h).zfill(2) for h in hours])
            plt.xlabel("Hour")
            plt.ylabel("Traffic Area (km2)")
            plt.title("Hourly Traffic Area by Class (km2) - Traffic Overlay Only")
            plt.legend(loc="upper right")
            plt.tight_layout()
            plt.savefig(bar_png, dpi=150)
            plt.close()
            feedback.pushInfo("Hourly bar chart written: " + bar_png)
        except Exception as e:
            feedback.pushWarning(f"Matplotlib bar plot failed: {e}")
            bar_png = ""

        try:
            plt.figure(figsize=(12, 4))
            x = np.arange(len(hours))
            plt.plot(x, cidx, marker="o")
            plt.xticks(x, [str(h).zfill(2) for h in hours])
            plt.xlabel("Hour")
            plt.ylabel("Hourly Mean Congestion Index")
            plt.title("Hourly Mean Congestion Index")
            plt.grid(True, which="both", axis="y", alpha=0.3)
            plt.tight_layout()
            plt.savefig(line_png, dpi=150)
            plt.close()
            feedback.pushInfo("Hourly line chart written: " + line_png)
        except Exception as e:
            feedback.pushWarning(f"Matplotlib line plot failed: {e}")
            line_png = ""

        return {"BAR_PNG": bar_png, "LINE_PNG": line_png}

    # -------------
    # Main
    # -------------

    def processAlgorithm(self, parameters, context, feedback):

        zmin = self.parameterAsInt(parameters, self.ZMIN, context)
        zmax = self.parameterAsInt(parameters, self.ZMAX, context)
        max_zoom_render = self.parameterAsInt(parameters, self.MAX_ZOOM_RENDER, context)
        max_dim_px = self.parameterAsInt(parameters, self.MAX_DIM_PX, context)

        if int(zmax) > int(max_zoom_render):
            raise QgsProcessingException(f"ZMAX too high. Max allowed is {int(max_zoom_render)}.")

        boundary_layer = self.parameterAsVectorLayer(parameters, self.BOUNDARY, context)
        if boundary_layer is None:
            raise QgsProcessingException("Boundary polygon is required.")

        out_folder = self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)
        if (not out_folder) or (out_folder == QgsProcessing.TEMPORARY_OUTPUT) or ("TEMPORARY_OUTPUT" in out_folder):
            out_folder = QgsProcessingUtils.tempFolder()
        if not out_folder:
            out_folder = QgsProcessingUtils.tempFolder()
        self._ensure_dir(out_folder)

        prefix = self.parameterAsString(parameters, self.FILE_PREFIX, context) or "xyz_"
        suffix = self.parameterAsString(parameters, self.FILE_SUFFIX, context) or ""

        do_clip = self.parameterAsBool(parameters, self.DO_CLIP, context)

        add_to_project = self.parameterAsBool(parameters, self.ADD_TO_PROJECT, context)
        group_name = (self.parameterAsString(parameters, self.GROUP_NAME, context) or "").strip()

        write_csv = self.parameterAsBool(parameters, self.WRITE_CSV, context)
        csv_name = (self.parameterAsString(parameters, self.CSV_NAME, context) or "xyz_weekly_index.csv").strip()

        do_classify = self.parameterAsBool(parameters, self.DO_CLASSIFY, context)
        alpha_min = self.parameterAsInt(parameters, self.ALPHA_MIN, context)
        sat_min = float(self.parameterAsDouble(parameters, self.SAT_MIN, context))

        w_free = float(self.parameterAsDouble(parameters, self.W_FREE, context))
        w_mod = float(self.parameterAsDouble(parameters, self.W_MOD, context))
        w_heavy = float(self.parameterAsDouble(parameters, self.W_HEAVY, context))
        w_sev = float(self.parameterAsDouble(parameters, self.W_SEV, context))

        gif_enable = self.parameterAsBool(parameters, self.GIF_ENABLE, context)
        gif_fps = float(self.parameterAsDouble(parameters, self.GIF_FPS, context))
        gif_seconds_per_frame = float(self.parameterAsDouble(parameters, self.GIF_SECONDS_PER_FRAME, context))
        gif_name = self.parameterAsString(parameters, self.GIF_NAME, context) or "traffic_animation.gif"

        plot_enable = self.parameterAsBool(parameters, self.PLOT_ENABLE, context)
        plot_bar_name = self.parameterAsString(parameters, self.PLOT_BAR_NAME, context) or "hourly_traffic_area_stacked.png"
        plot_line_name = self.parameterAsString(parameters, self.PLOT_LINE_NAME, context) or "hourly_mean_congestion_index.png"

        organize = self.parameterAsBool(parameters, self.ORGANIZE_OUTPUTS, context)
        scheme = self.parameterAsInt(parameters, self.FOLDER_SCHEME, context)
        if organize:
            dirs = self._prepare_output_structure(out_folder, scheme, feedback)
        else:
            dirs = self._prepare_output_structure(out_folder, 2, feedback)

        day_indices, hours = self._resolve_filters(parameters, context)
        if not day_indices:
            raise QgsProcessingException("No days selected.")
        if not hours:
            raise QgsProcessingException("No hours selected.")

        days = [
            ("Monday", 0),
            ("Tuesday", 1),
            ("Wednesday", 2),
            ("Thursday", 3),
            ("Friday", 4),
            ("Saturday", 5),
            ("Sunday", 6),
        ]
        day_lookup = {idx: name for name, idx in days}

        boundary_3857 = self._prepare_boundary_3857(boundary_layer, context, feedback)

        bbox_rect_3857 = boundary_3857.extent()
        if bbox_rect_3857 is None or bbox_rect_3857.isEmpty():
            raise QgsProcessingException("Boundary extent is empty after preparation.")

        project = QgsProject.instance()
        root = project.layerTreeRoot()
        main_group = None
        day_groups = {}

        if add_to_project:
            if not group_name:
                group_name = "Traffic XYZ Weekly"
            main_group = root.findGroup(group_name)
            if main_group is None:
                main_group = root.addGroup(group_name)
            for di in sorted(set(day_indices)):
                dn = day_lookup.get(di, f"Day_{di}")
                dg = main_group.findGroup(dn)
                if dg is None:
                    dg = main_group.addGroup(dn)
                day_groups[di] = dg

        combos = [(di, h) for di in sorted(set(day_indices)) for h in sorted(set(hours))]
        total = len(combos)

        csv_rows = []
        master_rows = []
        frame_paths = []
        n_ok = 0

        for k, (dindex, hour) in enumerate(combos, start=1):
            if feedback.isCanceled():
                break

            dname = day_lookup.get(dindex, f"Day_{dindex}")
            siw = (dindex * 86400) + (hour * 3600)

            uri = self._xyz_uri(self._FIXED_BASE_URL, siw, zmin, zmax)
            layer_title = f"{dname} {hour:02d}:00"

            rl = QgsRasterLayer(uri, layer_title, "wms")
            if not rl.isValid():
                feedback.pushWarning(f"Failed to create XYZ layer: {layer_title}")
                csv_rows.append({
                    "day_name": dname, "day_index": str(dindex), "hour": str(hour),
                    "seconds_into_week": str(siw), "layer_name": layer_title,
                    "output_tif": "", "status": "layer_invalid"
                })
                feedback.setProgress(int(100.0 * k / total))
                continue

            layer_key = f"{dname}_{hour:02d}00"
            out_name = self._safe_name(f"{prefix}{layer_key}{suffix}.tif")

            day_rasters_dir = self._subdir_for_day(dirs["rasters"], dname, dindex, dirs["scheme"])
            out_path = os.path.join(day_rasters_dir, out_name)

            tmp_bbox_path = os.path.join(dirs["tmp"], self._safe_name(f"bbox_{layer_key}.tif"))
            tmp_bbox_path = os.path.normpath(tmp_bbox_path)

            self._export_xyz_to_tif(rl, tmp_bbox_path, bbox_rect_3857, int(zmax), max_dim_px, feedback)

            if do_clip:
                processing.run("gdal:cliprasterbymasklayer", {
                    "INPUT": tmp_bbox_path,
                    "MASK": boundary_3857,
                    "SOURCE_CRS": None,
                    "TARGET_CRS": QgsCoordinateReferenceSystem("EPSG:3857"),
                    "NODATA": None,
                    "ALPHA_BAND": False,
                    "CROP_TO_CUTLINE": True,
                    "KEEP_RESOLUTION": True,
                    "SET_RESOLUTION": False,
                    "X_RESOLUTION": None,
                    "Y_RESOLUTION": None,
                    "MULTITHREADING": True,
                    "OPTIONS": "",
                    "DATA_TYPE": 0,
                    "EXTRA": "",
                    "OUTPUT": out_path
                }, context=context, feedback=feedback)
            else:
                processing.run("gdal:translate", {
                    "INPUT": tmp_bbox_path,
                    "TARGET_CRS": QgsCoordinateReferenceSystem("EPSG:3857"),
                    "NODATA": None,
                    "COPY_SUBDATASETS": False,
                    "OPTIONS": [],
                    "EXTRA": "",
                    "DATA_TYPE": 0,
                    "OUTPUT": out_path
                }, context=context, feedback=feedback)

            if os.path.exists(tmp_bbox_path):
                try:
                    os.remove(tmp_bbox_path)
                except Exception:
                    pass

            if add_to_project:
                r_final = QgsRasterLayer(out_path, f"{layer_title} traffic", "gdal")
                if r_final.isValid():
                    project.addMapLayer(r_final, False)
                    day_groups[dindex].addLayer(r_final)

            class_tif = ""
            cindex_tif = ""
            if do_classify and os.path.exists(out_path):
                day_classes_dir = self._subdir_for_day(dirs["classes"], dname, dindex, dirs["scheme"])
                day_cindex_dir = self._subdir_for_day(dirs["cindex"], dname, dindex, dirs["scheme"])
                day_tables_dir = self._subdir_for_day(dirs["tables"], dname, dindex, dirs["scheme"])

                class_tif = os.path.join(day_classes_dir, self._safe_name(f"{prefix}{layer_key}{suffix}_class.tif"))
                cindex_tif = os.path.join(day_cindex_dir, self._safe_name(f"{prefix}{layer_key}{suffix}_cindex.tif"))
                class_csv = os.path.join(day_tables_dir, self._safe_name(f"{prefix}{layer_key}{suffix}_class_table.csv"))

                try:
                    summary, mean_idx = self._classify_hsv_traffic(
                        out_path, class_tif, cindex_tif, class_csv,
                        alpha_min, sat_min, w_free, w_mod, w_heavy, w_sev, feedback
                    )

                    if add_to_project:
                        r_class = QgsRasterLayer(class_tif, f"{layer_title} class", "gdal")
                        r_idx = QgsRasterLayer(cindex_tif, f"{layer_title} cindex", "gdal")
                        if r_class.isValid():
                            project.addMapLayer(r_class, False)
                            day_groups[dindex].addLayer(r_class)
                        if r_idx.isValid():
                            project.addMapLayer(r_idx, False)
                            day_groups[dindex].addLayer(r_idx)

                    free_km2 = summary.get("1", {}).get("km2", 0.0)
                    mod_km2 = summary.get("2", {}).get("km2", 0.0)
                    heavy_km2 = summary.get("3", {}).get("km2", 0.0)
                    sev_km2 = summary.get("4", {}).get("km2", 0.0)

                    master_rows.append({
                        "day_name": dname,
                        "day_index": str(dindex),
                        "hour": str(hour),
                        "seconds_into_week": str(siw),
                        "out_tif": out_path,
                        "free_km2": f"{free_km2:.6f}",
                        "moderate_km2": f"{mod_km2:.6f}",
                        "heavy_km2": f"{heavy_km2:.6f}",
                        "severe_km2": f"{sev_km2:.6f}",
                        "mean_cindex": f"{mean_idx:.6f}"
                    })
                except Exception as e:
                    feedback.pushWarning(f"Classification failed for {layer_title}: {e}")

            if gif_enable and os.path.exists(out_path):
                day_frames_dir = self._subdir_for_day(dirs["frames"], dname, dindex, dirs["scheme"])
                frame_png = os.path.join(day_frames_dir, self._safe_name(f"{prefix}{layer_key}{suffix}.png"))
                label = f"{dname} {hour:02d}:00"
                try:
                    self._tif_to_png_with_label(out_path, frame_png, label, context, feedback)
                    if os.path.exists(frame_png):
                        frame_paths.append(frame_png)
                except Exception as e:
                    feedback.pushWarning(f"Frame export failed for {layer_title}: {e}")

            n_ok += 1
            csv_rows.append({
                "day_name": dname,
                "day_index": str(dindex),
                "hour": str(hour),
                "seconds_into_week": str(siw),
                "layer_name": layer_title,
                "output_tif": out_path,
                "status": "ok"
            })

            feedback.setProgress(int(100.0 * k / total))

        csv_path = ""
        if write_csv:
            csv_path = os.path.join(dirs["meta"], self._safe_name(csv_name))
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["day_name", "day_index", "hour", "seconds_into_week", "layer_name", "output_tif", "status"]
                )
                writer.writeheader()
                for r in csv_rows:
                    writer.writerow(r)
            feedback.pushInfo("CSV written: " + csv_path)

        master_csv = ""
        if master_rows:
            master_csv = os.path.join(dirs["tables"], "traffic_class_summary.csv")
            with open(master_csv, "w", newline="", encoding="utf-8") as f:
                fn = ["day_name", "day_index", "hour", "seconds_into_week", "out_tif",
                      "free_km2", "moderate_km2", "heavy_km2", "severe_km2", "mean_cindex"]
                w = csv.DictWriter(f, fieldnames=fn)
                w.writeheader()
                for r in master_rows:
                    w.writerow(r)
            feedback.pushInfo("Master class summary CSV written: " + master_csv)

        plot_bar_png = ""
        plot_line_png = ""
        if plot_enable and master_csv and os.path.exists(master_csv):
            plots = self._make_hourly_plots(master_csv, dirs["products"], plot_bar_name, plot_line_name, feedback)
            plot_bar_png = plots.get("BAR_PNG", "")
            plot_line_png = plots.get("LINE_PNG", "")

        gif_path = ""
        if gif_enable and frame_paths:
            gif_path = os.path.join(dirs["products"], self._safe_name(gif_name))
            self._write_gif(frame_paths, gif_path, gif_fps, gif_seconds_per_frame, feedback)

        feedback.pushInfo(f"Completed. Exported ok: {n_ok} of {total}")

        return {
            "OUTPUT_FOLDER": out_folder,
            "CSV_PATH": csv_path,
            "EXPORTED_OK": n_ok,
            "REQUESTED": total,
            "MASTER_CLASS_CSV": master_csv,
            "GIF_PATH": gif_path,
            "PLOT_BAR_PNG": plot_bar_png,
            "PLOT_LINE_PNG": plot_line_png
        }
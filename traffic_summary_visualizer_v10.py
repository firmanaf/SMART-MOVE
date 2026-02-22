# -*- coding: utf-8 -*-
"""
QGIS Processing Toolbox Script
Name: Traffic Summary Visualizer (from traffic_class_summary.csv) v1.0
Author: Firman Afrianto, Maya Safira
License: GPL-2.0-or-later

Ringkas
Tool ini membaca CSV keluaran Google Traffic Analyzer (traffic_class_summary.csv) dan membuat:
A) 2 PNG dasar
   1) Hourly Traffic Area by Class (stacked bar, traffic overlay only, tanpa Unknown dan tanpa abu abu)
   2) Hourly Mean Congestion Index (line)

B) 12 output lanjutan
   01 Heatmap jam vs hari (Mean Congestion Index)
   02 Traffic dominance timeline (kelas dominan tiap jam)
   03 Congestion phase diagram (proxy regime)
   04 Rush hour detector plot
   04 Rush hour detector CSV
   05 Temporal clustering heatmap (KMeans)
   06 Animated congestion curve (GIF)
   07 Radar profile per hari
   08 Peak detection labeled (week timeline)
   09 Urban traffic signature curve (mean)
   10 Weekday vs weekend cindex
   10 Weekday vs weekend area
   11 Signature metrics per day (bar)
   12 Variability per hour (std across days)

Catatan penting
- CSV yang dibaca adalah traffic_class_summary.csv yang punya kolom:
  day_name, day_index, hour, free_km2, moderate_km2, heavy_km2, severe_km2, unknown_km2, mean_cindex
- Kelas "Unknown" diabaikan.
- Piksel abu abu pada peta (non traffic) seharusnya tidak ikut masuk karena bukan bagian kelas 1..4.
  Jika dataset Anda masih menyimpan abu abu ke "unknown_km2", tool ini juga mengabaikan unknown.

Dependensi
- matplotlib (wajib untuk PNG)
- numpy (umumnya ada)
- imageio (opsional, untuk GIF)

"""

import os
import csv
import math

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.core import QgsProcessingOutputFolder

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFile,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsProcessingParameterEnum,
    QgsProcessingUtils
)

import numpy as np

# matplotlib (wajib untuk output PNG)
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except Exception:
    plt = None

# GIF
try:
    import imageio.v2 as imageio
except Exception:
    imageio = None


class TrafficSummaryVisualizerV10(QgsProcessingAlgorithm):

    IN_CSV = "IN_CSV"
    OUT_FOLDER = "OUT_FOLDER"
    MAKE_GIF = "MAKE_GIF"
    GIF_FPS = "GIF_FPS"
    GIF_SECONDS_PER_FRAME = "GIF_SECONDS_PER_FRAME"
    GIF_NAME = "GIF_NAME"

    CLUSTER_K = "CLUSTER_K"
    PEAK_PROM_FRAC = "PEAK_PROM_FRAC"

    TITLE_PREFIX = "TITLE_PREFIX"

    def tr(self, s):
        return QCoreApplication.translate("TrafficSummaryVisualizerV10", s)

    def name(self):
        return "traffic_summary_visualizer_v10"

    def displayName(self):
        return self.tr("Traffic Summary Visualizer")

    def group(self):
        return self.tr('SMART-MOVE Mobility Analytics')
    
    def groupId(self):
        return 'transportsimulation'

    def createInstance(self):
        return TrafficSummaryVisualizerV10()

    def shortHelpString(self):
        return self.tr(
            "<p><b>Created By: Firman Afrianto, Maya Safira</b></p>"
            "<p>Reads <b>traffic_class_summary.csv</b> (Traffic Analyzer output) and produces a set of PNG/GIF charts for hourly and weekly traffic dynamics.</p>"

            "<p><b>Inputs</b></p>"
            "<ul>"
            "<li><b>CSV</b>: <i>traffic_class_summary.csv</i></li>"
            "</ul>"

            "<p><b>What it produces</b></p>"
            "<p><b>A) 2 base PNG outputs</b></p>"
            "<ol>"
            "<li><b>Hourly Traffic Area by Class</b> (stacked bar, traffic overlay only, excluding <i>Unknown</i> and excluding gray/non-traffic pixels)</li>"
            "<li><b>Hourly Mean Congestion Index</b> (line chart)</li>"
            "</ol>"

            "<p><b>B) 12 advanced outputs</b></p>"
            "<ol>"
            "<li>Heatmap: <b>Hour × Day</b> (Mean Congestion Index)</li>"
            "<li><b>Traffic dominance timeline</b> (dominant class per hour)</li>"
            "<li><b>Congestion phase diagram</b> (proxy regime)</li>"
            "<li><b>Rush hour detector</b> plot</li>"
            "<li><b>Rush hour detector</b> CSV</li>"
            "<li><b>Temporal clustering heatmap</b> (KMeans)</li>"
            "<li><b>Animated congestion curve</b> (GIF)</li>"
            "<li><b>Radar profile</b> per day</li>"
            "<li><b>Peak detection</b> labeled (week timeline)</li>"
            "<li><b>Urban traffic signature</b> curve (mean)</li>"
            "<li><b>Weekday vs weekend</b>: cindex comparison</li>"
            "<li><b>Weekday vs weekend</b>: area comparison</li>"
            "<li><b>Signature metrics</b> per day (bar)</li>"
            "<li><b>Variability per hour</b> (std across days)</li>"
            "</ol>"

            "<p><b>Expected CSV schema</b></p>"
            "<p>The CSV must contain the following columns:</p>"
            "<ul>"
            "<li><code>day_name</code>, <code>day_index</code>, <code>hour</code></li>"
            "<li><code>free_km2</code>, <code>moderate_km2</code>, <code>heavy_km2</code>, <code>severe_km2</code>, <code>unknown_km2</code></li>"
            "<li><code>mean_cindex</code></li>"
            "</ul>"

            "<p><b>Important notes</b></p>"
            "<ul>"
            "<li>The <b>Unknown</b> class is always ignored.</li>"
            "<li>Gray/non-traffic pixels should not be included because they are not part of classes 1..4.</li>"
            "<li>If your dataset still stores gray pixels into <code>unknown_km2</code>, this tool still ignores them by ignoring <b>Unknown</b>.</li>"
            "</ul>"

            "<p><b>Dependencies</b></p>"
            "<ul>"
            "<li><b>matplotlib</b> (required for PNG outputs)</li>"
            "<li><b>numpy</b> (usually available)</li>"
            "<li><b>imageio</b> (optional, for GIF export)</li>"
            "</ul>"
        )

    def initAlgorithm(self, config=None):

        self.addParameter(QgsProcessingParameterFile(
            self.IN_CSV, self.tr("Input traffic_class_summary.csv"),
            behavior=QgsProcessingParameterFile.File,
            fileFilter="CSV (*.csv)"
        ))

        self.addParameter(QgsProcessingParameterFolderDestination(
            self.OUT_FOLDER, self.tr("Output folder")
        ))

        self.addParameter(QgsProcessingParameterBoolean(
            self.MAKE_GIF, self.tr("Create animated congestion curve GIF (requires imageio)"),
            defaultValue=True
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.GIF_FPS, self.tr("GIF FPS (used if seconds per frame is empty)"),
            type=QgsProcessingParameterNumber.Double, defaultValue=2.0, minValue=0.1, maxValue=60.0
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.GIF_SECONDS_PER_FRAME, self.tr("GIF seconds per frame (optional, overrides FPS)"),
            type=QgsProcessingParameterNumber.Double, defaultValue=0.0, minValue=0.0, maxValue=60.0
        ))
        self.addParameter(QgsProcessingParameterString(
            self.GIF_NAME, self.tr("GIF filename"),
            defaultValue="06_animated_congestion_curve.gif",
            optional=True
        ))

        self.addParameter(QgsProcessingParameterNumber(
            self.CLUSTER_K, self.tr("Temporal clustering: number of clusters (KMeans-like)"),
            type=QgsProcessingParameterNumber.Integer, defaultValue=3, minValue=2, maxValue=10
        ))

        self.addParameter(QgsProcessingParameterNumber(
            self.PEAK_PROM_FRAC, self.tr("Peak detection sensitivity (0.05 to 0.50, higher means fewer peaks)"),
            type=QgsProcessingParameterNumber.Double, defaultValue=0.20, minValue=0.05, maxValue=0.50
        ))

        self.addParameter(QgsProcessingParameterString(
            self.TITLE_PREFIX, self.tr("Figure title prefix (optional)"),
            defaultValue="",
            optional=True
        ))
        
        self.addOutput(QgsProcessingOutputFolder("OUT_FOLDER", self.tr("Output folder (clickable in Results)")))

    # -------------------------
    # Utilities
    # -------------------------

    def _ensure_folder(self, folder):
        if not folder or folder == QgsProcessing.TEMPORARY_OUTPUT or "TEMPORARY_OUTPUT" in str(folder):
            folder = QgsProcessingUtils.tempFolder()
        os.makedirs(folder, exist_ok=True)
        return folder

    def _safe_path(self, folder, name):
        name = (name or "").strip()
        if not name:
            name = "output.png"
        return os.path.join(folder, name)

    def _read_csv(self, path):
        rows = []
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                if not r:
                    continue
                def fnum(k):
                    try:
                        return float(r.get(k, "0") or 0.0)
                    except Exception:
                        return 0.0
                def fint(k):
                    try:
                        return int(float(r.get(k, "0") or 0))
                    except Exception:
                        return 0

                rows.append({
                    "day_name": (r.get("day_name", "") or "").strip(),
                    "day_index": fint("day_index"),
                    "hour": fint("hour"),
                    "free_km2": fnum("free_km2"),
                    "moderate_km2": fnum("moderate_km2"),
                    "heavy_km2": fnum("heavy_km2"),
                    "severe_km2": fnum("severe_km2"),
                    "unknown_km2": fnum("unknown_km2"),
                    "mean_cindex": fnum("mean_cindex"),
                })
        return rows

    def _pivot_day_hour(self, rows):
        # returns dict day -> hour -> metrics (averaged if duplicates exist)
        days = sorted(set([r["day_name"] for r in rows if r["day_name"]]))
        # stable order by day_index where possible
        day_order = sorted(
            [(d, min([rr["day_index"] for rr in rows if rr["day_name"] == d] or [999])) for d in days],
            key=lambda x: x[1]
        )
        days = [d for d, _ in day_order]

        hours = list(range(24))
        agg = {}
        for d in days:
            agg[d] = {}
            for h in hours:
                agg[d][h] = {"n": 0, "free": 0.0, "mod": 0.0, "heavy": 0.0, "sev": 0.0, "cidx": 0.0}
        for r in rows:
            d = r["day_name"]
            h = r["hour"]
            if d not in agg or h not in agg[d]:
                continue
            agg[d][h]["n"] += 1
            agg[d][h]["free"] += r["free_km2"]
            agg[d][h]["mod"] += r["moderate_km2"]
            agg[d][h]["heavy"] += r["heavy_km2"]
            agg[d][h]["sev"] += r["severe_km2"]
            agg[d][h]["cidx"] += r["mean_cindex"]

        # average
        out = {}
        for d in days:
            out[d] = {}
            for h in hours:
                n = max(1, agg[d][h]["n"])
                out[d][h] = {
                    "free": agg[d][h]["free"] / n,
                    "mod": agg[d][h]["mod"] / n,
                    "heavy": agg[d][h]["heavy"] / n,
                    "sev": agg[d][h]["sev"] / n,
                    "cidx": agg[d][h]["cidx"] / n
                }
        return days, hours, out

    def _weekday_weekend(self, day_name):
        # Monday..Sunday
        dn = (day_name or "").lower()
        if dn.startswith("sat") or dn.startswith("sun"):
            return "Weekend"
        if dn.startswith("mon") or dn.startswith("tue") or dn.startswith("wed") or dn.startswith("thu") or dn.startswith("fri"):
            return "Weekday"
        return "Unknown"

    def _dominant_class(self, free, mod, heavy, sev):
        vals = {"Free": free, "Moderate": mod, "Heavy": heavy, "Severe": sev}
        # dominant among traffic overlay only
        if (free + mod + heavy + sev) <= 0:
            return "None"
        return max(vals.items(), key=lambda x: x[1])[0]

    def _simple_kmeans(self, X, k, iters=50, seed=7):
        # X: n x m
        rng = np.random.default_rng(seed)
        n = X.shape[0]
        if n <= k:
            return np.arange(n)
        # init centers
        idx = rng.choice(n, size=k, replace=False)
        centers = X[idx].copy()
        labels = np.zeros(n, dtype=int)
        for _ in range(iters):
            # assign
            d2 = ((X[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
            new_labels = d2.argmin(axis=1)
            if np.all(new_labels == labels):
                break
            labels = new_labels
            # update
            for j in range(k):
                mask = labels == j
                if mask.sum() > 0:
                    centers[j] = X[mask].mean(axis=0)
        return labels

    def _detect_peaks_simple(self, y, prom_frac=0.2):
        # return list of peak indices
        y = np.asarray(y, dtype=float)
        if y.size < 3:
            return []
        rng = float(y.max() - y.min())
        prom = prom_frac * (rng if rng > 0 else 1.0)
        peaks = []
        for i in range(1, len(y) - 1):
            if y[i] > y[i-1] and y[i] >= y[i+1]:
                # local prominence proxy
                left_min = float(np.min(y[max(0, i-3):i]))
                right_min = float(np.min(y[i+1:min(len(y), i+4)]))
                if (y[i] - max(left_min, right_min)) >= prom:
                    peaks.append(i)
        return peaks

    def _write_gif(self, png_paths, gif_path, fps, seconds_per_frame, feedback):
        if imageio is None:
            feedback.pushWarning("imageio not available, skipping GIF.")
            return False
        frames = [imageio.imread(p) for p in png_paths if os.path.exists(p)]
        if not frames:
            feedback.pushWarning("No frames found for GIF.")
            return False

        seconds_per_frame = float(seconds_per_frame) if seconds_per_frame is not None else 0.0
        fps = float(fps) if fps is not None else 2.0

        if seconds_per_frame > 0:
            duration = max(0.1, seconds_per_frame)
        else:
            duration = 1.0 / max(0.001, fps)

        imageio.mimsave(gif_path, frames, duration=duration)
        feedback.pushInfo("GIF written: " + gif_path)
        return True

    # -------------------------
    # Plot builders
    # -------------------------

    def _require_matplotlib(self):
        if plt is None:
            raise QgsProcessingException("matplotlib is not available. Please install matplotlib in your QGIS Python environment.")

    def _plot_base_stacked_area(self, days, hours, data, out_png, title_prefix=""):
        self._require_matplotlib()

        # average across days per hour
        free = []
        mod = []
        heavy = []
        sev = []
        for h in hours:
            vals = [data[d][h] for d in days]
            free.append(float(np.mean([v["free"] for v in vals])))
            mod.append(float(np.mean([v["mod"] for v in vals])))
            heavy.append(float(np.mean([v["heavy"] for v in vals])))
            sev.append(float(np.mean([v["sev"] for v in vals])))

        x = np.arange(len(hours))
        b1 = np.array(free)
        b2 = np.array(mod)
        b3 = np.array(heavy)
        b4 = np.array(sev)

        plt.figure(figsize=(14, 6))
        plt.bar(x, b1, label="Free (Green)")
        plt.bar(x, b2, bottom=b1, label="Moderate (Orange)")
        plt.bar(x, b3, bottom=b1 + b2, label="Heavy (Red)")
        plt.bar(x, b4, bottom=b1 + b2 + b3, label="Severe (Dark Red)")
        plt.xticks(x, [str(h).zfill(2) for h in hours])
        plt.xlabel("Hour")
        plt.ylabel("Traffic Area (km2)")
        ttl = "Hourly Traffic Area by Class (km2) - Traffic Overlay Only"
        if title_prefix:
            ttl = f"{title_prefix} {ttl}"
        plt.title(ttl)
        plt.legend(loc="upper right")
        plt.tight_layout()
        plt.savefig(out_png, dpi=150)
        plt.close()

    def _plot_base_line_cindex(self, days, hours, data, out_png, title_prefix=""):
        self._require_matplotlib()

        cidx = []
        for h in hours:
            vals = [data[d][h] for d in days]
            cidx.append(float(np.mean([v["cidx"] for v in vals])))

        x = np.arange(len(hours))
        plt.figure(figsize=(14, 5))
        plt.plot(x, cidx, marker="o")
        plt.xticks(x, [str(h).zfill(2) for h in hours])
        plt.xlabel("Hour")
        plt.ylabel("Mean Congestion Index")
        ttl = "Hourly Mean Congestion Index"
        if title_prefix:
            ttl = f"{title_prefix} {ttl}"
        plt.title(ttl)
        plt.grid(True, axis="y", alpha=0.3)
        plt.tight_layout()
        plt.savefig(out_png, dpi=150)
        plt.close()

    def _plot_heatmap_day_hour(self, days, hours, data, out_png, title_prefix=""):
        self._require_matplotlib()

        M = np.zeros((len(days), len(hours)), dtype=float)
        for i, d in enumerate(days):
            for j, h in enumerate(hours):
                M[i, j] = data[d][h]["cidx"]

        plt.figure(figsize=(14, 6))
        plt.imshow(M, aspect="auto")
        plt.colorbar(label="Mean Congestion Index")
        plt.yticks(np.arange(len(days)), days)
        plt.xticks(np.arange(len(hours)), [str(h).zfill(2) for h in hours], rotation=0)
        ttl = "Heatmap Day x Hour (Mean Congestion Index)"
        if title_prefix:
            ttl = f"{title_prefix} {ttl}"
        plt.title(ttl)
        plt.xlabel("Hour")
        plt.ylabel("Day")
        plt.tight_layout()
        plt.savefig(out_png, dpi=150)
        plt.close()

    def _plot_dominance_timeline(self, days, hours, data, out_png, title_prefix=""):
        self._require_matplotlib()

        # build categorical matrix: day x hour as integer codes
        classes = ["None", "Free", "Moderate", "Heavy", "Severe"]
        code = {c: i for i, c in enumerate(classes)}

        M = np.zeros((len(days), len(hours)), dtype=int)
        for i, d in enumerate(days):
            for j, h in enumerate(hours):
                v = data[d][h]
                dom = self._dominant_class(v["free"], v["mod"], v["heavy"], v["sev"])
                M[i, j] = code.get(dom, 0)

        plt.figure(figsize=(14, 6))
        plt.imshow(M, aspect="auto", vmin=0, vmax=len(classes)-1)
        cbar = plt.colorbar()
        cbar.set_ticks(list(range(len(classes))))
        cbar.set_ticklabels(classes)
        plt.yticks(np.arange(len(days)), days)
        plt.xticks(np.arange(len(hours)), [str(h).zfill(2) for h in hours], rotation=0)
        ttl = "Traffic Dominance Timeline (Dominant Class per Hour)"
        if title_prefix:
            ttl = f"{title_prefix} {ttl}"
        plt.title(ttl)
        plt.xlabel("Hour")
        plt.ylabel("Day")
        plt.tight_layout()
        plt.savefig(out_png, dpi=150)
        plt.close()

    def _plot_phase_diagram(self, days, hours, data, out_png, title_prefix=""):
        self._require_matplotlib()

        # proxy axes:
        # x = total traffic overlay area (km2)
        # y = mean congestion index
        xs = []
        ys = []
        labels = []
        for d in days:
            for h in hours:
                v = data[d][h]
                area = v["free"] + v["mod"] + v["heavy"] + v["sev"]
                xs.append(area)
                ys.append(v["cidx"])
                labels.append(f"{d} {h:02d}")

        plt.figure(figsize=(9, 7))
        plt.scatter(xs, ys, s=18)
        ttl = "Congestion Phase Diagram (proxy regime)"
        if title_prefix:
            ttl = f"{title_prefix} {ttl}"
        plt.title(ttl)
        plt.xlabel("Traffic Overlay Area (km2)")
        plt.ylabel("Mean Congestion Index")
        plt.grid(True, alpha=0.25)
        plt.tight_layout()
        plt.savefig(out_png, dpi=150)
        plt.close()

    def _rush_hour_detector(self, days, hours, data, out_png, out_csv, prom_frac=0.2, title_prefix=""):
        self._require_matplotlib()

        # per day peak detection on cidx curve
        out_rows = []
        plt.figure(figsize=(14, 6))
        x = np.arange(len(hours))

        for d in days:
            y = np.array([data[d][h]["cidx"] for h in hours], dtype=float)
            peaks = self._detect_peaks_simple(y, prom_frac=prom_frac)

            plt.plot(x, y, marker="o", linewidth=1.2, label=d)
            for p in peaks:
                plt.text(p, y[p], f"{hours[p]:02d}", fontsize=8)

            if peaks:
                out_rows.append({
                    "day_name": d,
                    "peak_hours": ";".join([str(hours[p]).zfill(2) for p in peaks]),
                    "peak_count": str(len(peaks)),
                    "max_cindex": f"{float(np.max(y)):.6f}"
                })
            else:
                out_rows.append({
                    "day_name": d,
                    "peak_hours": "",
                    "peak_count": "0",
                    "max_cindex": f"{float(np.max(y)):.6f}"
                })

        ttl = "Rush Hour Detector (peaks labeled by hour)"
        if title_prefix:
            ttl = f"{title_prefix} {ttl}"
        plt.title(ttl)
        plt.xticks(x, [str(h).zfill(2) for h in hours])
        plt.xlabel("Hour")
        plt.ylabel("Mean Congestion Index")
        plt.grid(True, axis="y", alpha=0.25)
        plt.legend(loc="upper right")
        plt.tight_layout()
        plt.savefig(out_png, dpi=150)
        plt.close()

        with open(out_csv, "w", encoding="utf-8", newline="") as f:
            fn = ["day_name", "peak_hours", "peak_count", "max_cindex"]
            w = csv.DictWriter(f, fieldnames=fn)
            w.writeheader()
            for r in out_rows:
                w.writerow(r)

    def _temporal_clustering_heatmap(self, days, hours, data, out_png, k=3, title_prefix=""):
        self._require_matplotlib()

        # clustering on day vectors of cidx
        X = np.vstack([np.array([data[d][h]["cidx"] for h in hours], dtype=float) for d in days])
        labels = self._simple_kmeans(X, k=int(k))

        # reorder days by cluster then by mean level
        day_stats = []
        for i, d in enumerate(days):
            day_stats.append((labels[i], float(X[i].mean()), d, i))
        day_stats.sort(key=lambda t: (t[0], t[1]))
        order = [t[2] for t in day_stats]
        M = np.vstack([np.array([data[d][h]["cidx"] for h in hours], dtype=float) for d in order])

        plt.figure(figsize=(14, 6))
        plt.imshow(M, aspect="auto")
        plt.colorbar(label="Mean Congestion Index")
        plt.yticks(np.arange(len(order)), [f"{d} (C{labels[days.index(d)]})" for d in order])
        plt.xticks(np.arange(len(hours)), [str(h).zfill(2) for h in hours], rotation=0)
        ttl = f"Temporal Clustering Heatmap (K={int(k)})"
        if title_prefix:
            ttl = f"{title_prefix} {ttl}"
        plt.title(ttl)
        plt.xlabel("Hour")
        plt.ylabel("Day")
        plt.tight_layout()
        plt.savefig(out_png, dpi=150)
        plt.close()

    def _animated_congestion_curve(self, days, hours, data, out_folder, gif_name, fps, spf, title_prefix=""):
        self._require_matplotlib()
        # create frames per day, per hour showing cumulative reveal
        frame_paths = []
        x = np.arange(len(hours))

        for d in days:
            y = np.array([data[d][h]["cidx"] for h in hours], dtype=float)
            for j in range(len(hours)):
                plt.figure(figsize=(10, 4))
                plt.plot(x[:j+1], y[:j+1], marker="o")
                plt.xlim(0, len(hours)-1)
                ymin = float(np.min(y))
                ymax = float(np.max(y))
                pad = 0.05 * (ymax - ymin if ymax > ymin else 1.0)
                plt.ylim(ymin - pad, ymax + pad)
                plt.xticks(x, [str(h).zfill(2) for h in hours])
                plt.xlabel("Hour")
                plt.ylabel("Mean Congestion Index")
                ttl = f"Animated Congestion Curve: {d} up to {hours[j]:02d}:00"
                if title_prefix:
                    ttl = f"{title_prefix} {ttl}"
                plt.title(ttl)
                plt.grid(True, axis="y", alpha=0.25)
                plt.tight_layout()

                frame = os.path.join(out_folder, f"__frame_{d}_{hours[j]:02d}.png")
                plt.savefig(frame, dpi=120)
                plt.close()
                frame_paths.append(frame)

        gif_name = os.path.basename(gif_name)
        gif_path = os.path.join(out_folder, gif_name)

        ok = self._write_gif(frame_paths, gif_path, fps, spf, feedback=self._gif_feedback_proxy())

        # cleanup frames
        for p in frame_paths:
            try:
                os.remove(p)
            except Exception:
                pass

        return gif_path if ok else ""

    def _gif_feedback_proxy(self):
        # minimal proxy to avoid passing feedback everywhere inside plotting function
        class _F:
            def pushWarning(self, s): pass
            def pushInfo(self, s): pass
        return _F()

    def _radar_profile_per_day(self, days, hours, data, out_png, title_prefix=""):
        self._require_matplotlib()

        # radar of normalized cidx per day
        angles = np.linspace(0, 2*np.pi, len(hours), endpoint=False)
        angles = np.concatenate([angles, [angles[0]]])

        plt.figure(figsize=(10, 8))
        ax = plt.subplot(111, polar=True)

        for d in days:
            y = np.array([data[d][h]["cidx"] for h in hours], dtype=float)
            # normalize to 0..1 for comparability
            lo = float(y.min())
            hi = float(y.max())
            yn = (y - lo) / (hi - lo) if hi > lo else y * 0.0
            yn = np.concatenate([yn, [yn[0]]])
            ax.plot(angles, yn, linewidth=1.5, label=d)

        ax.set_xticks(np.linspace(0, 2*np.pi, len(hours), endpoint=False))
        ax.set_xticklabels([str(h).zfill(2) for h in hours])
        ttl = "Radar Profile per Day (Normalized Cindex)"
        if title_prefix:
            ttl = f"{title_prefix} {ttl}"
        ax.set_title(ttl, pad=20)
        ax.legend(loc="upper right", bbox_to_anchor=(1.25, 1.10))
        plt.tight_layout()
        plt.savefig(out_png, dpi=150)
        plt.close()

    def _peak_detection_week_timeline(self, rows, out_png, prom_frac=0.2, title_prefix=""):
        self._require_matplotlib()

        # sort by day_index then hour
        rows2 = sorted(rows, key=lambda r: (r["day_index"], r["hour"]))
        y = np.array([r["mean_cindex"] for r in rows2], dtype=float)
        x = np.arange(len(rows2))

        peaks = self._detect_peaks_simple(y, prom_frac=prom_frac)

        plt.figure(figsize=(16, 5))
        plt.plot(x, y, marker="o", linewidth=1.0)
        for p in peaks:
            d = rows2[p]["day_name"]
            h = rows2[p]["hour"]
            plt.text(p, y[p], f"{d[:3]} {h:02d}", fontsize=8)

        ttl = "Peak Detection (Week Timeline) with Auto Labels"
        if title_prefix:
            ttl = f"{title_prefix} {ttl}"
        plt.title(ttl)
        plt.xlabel("Time step (day hour sequence)")
        plt.ylabel("Mean Congestion Index")
        plt.grid(True, axis="y", alpha=0.25)
        plt.tight_layout()
        plt.savefig(out_png, dpi=150)
        plt.close()

    def _urban_signature_curve(self, days, hours, data, out_png, title_prefix=""):
        self._require_matplotlib()

        mean = []
        p10 = []
        p90 = []
        for h in hours:
            vals = np.array([data[d][h]["cidx"] for d in days], dtype=float)
            mean.append(float(vals.mean()))
            p10.append(float(np.percentile(vals, 10)))
            p90.append(float(np.percentile(vals, 90)))

        x = np.arange(len(hours))
        plt.figure(figsize=(14, 5))
        plt.plot(x, mean, marker="o", label="Mean")
        plt.fill_between(x, p10, p90, alpha=0.2, label="P10 to P90")
        plt.xticks(x, [str(h).zfill(2) for h in hours])
        plt.xlabel("Hour")
        plt.ylabel("Mean Congestion Index")
        ttl = "Urban Traffic Signature Curve"
        if title_prefix:
            ttl = f"{title_prefix} {ttl}"
        plt.title(ttl)
        plt.grid(True, axis="y", alpha=0.25)
        plt.legend(loc="upper right")
        plt.tight_layout()
        plt.savefig(out_png, dpi=150)
        plt.close()

    def _weekday_weekend_compare(self, days, hours, data, out_png_cidx, out_png_area, title_prefix=""):
        self._require_matplotlib()

        groups = {"Weekday": [], "Weekend": []}
        for d in days:
            g = self._weekday_weekend(d)
            if g in groups:
                groups[g].append(d)

        # cindex compare
        x = np.arange(len(hours))
        plt.figure(figsize=(14, 5))
        for gname, dlist in groups.items():
            if not dlist:
                continue
            y = [float(np.mean([data[d][h]["cidx"] for d in dlist])) for h in hours]
            plt.plot(x, y, marker="o", label=gname)

        plt.xticks(x, [str(h).zfill(2) for h in hours])
        plt.xlabel("Hour")
        plt.ylabel("Mean Congestion Index")
        ttl = "Comparative Weekday vs Weekend (Cindex)"
        if title_prefix:
            ttl = f"{title_prefix} {ttl}"
        plt.title(ttl)
        plt.grid(True, axis="y", alpha=0.25)
        plt.legend(loc="upper right")
        plt.tight_layout()
        plt.savefig(out_png_cidx, dpi=150)
        plt.close()

        # area compare (total traffic overlay)
        plt.figure(figsize=(14, 5))
        for gname, dlist in groups.items():
            if not dlist:
                continue
            y = []
            for h in hours:
                area = []
                for d in dlist:
                    v = data[d][h]
                    area.append(v["free"] + v["mod"] + v["heavy"] + v["sev"])
                y.append(float(np.mean(area)))
            plt.plot(x, y, marker="o", label=gname)

        plt.xticks(x, [str(h).zfill(2) for h in hours])
        plt.xlabel("Hour")
        plt.ylabel("Traffic Overlay Area (km2)")
        ttl = "Comparative Weekday vs Weekend (Traffic Overlay Area)"
        if title_prefix:
            ttl = f"{title_prefix} {ttl}"
        plt.title(ttl)
        plt.grid(True, axis="y", alpha=0.25)
        plt.legend(loc="upper right")
        plt.tight_layout()
        plt.savefig(out_png_area, dpi=150)
        plt.close()

    def _signature_metrics_per_day(self, days, hours, data, out_png, out_csv, title_prefix=""):
        self._require_matplotlib()

        # compute per day metrics
        out_rows = []
        for d in days:
            y = np.array([data[d][h]["cidx"] for h in hours], dtype=float)
            out_rows.append({
                "day_name": d,
                "mean_cindex": float(y.mean()),
                "max_cindex": float(y.max()),
                "min_cindex": float(y.min()),
                "std_cindex": float(y.std())
            })

        # bar plot mean per day
        names = [r["day_name"] for r in out_rows]
        means = [r["mean_cindex"] for r in out_rows]

        x = np.arange(len(names))
        plt.figure(figsize=(12, 5))
        plt.bar(x, means)
        plt.xticks(x, names, rotation=20, ha="right")
        plt.ylabel("Mean Congestion Index")
        ttl = "Signature Metrics per Day (Mean Cindex)"
        if title_prefix:
            ttl = f"{title_prefix} {ttl}"
        plt.title(ttl)
        plt.tight_layout()
        plt.savefig(out_png, dpi=150)
        plt.close()

        with open(out_csv, "w", encoding="utf-8", newline="") as f:
            fn = ["day_name", "mean_cindex", "max_cindex", "min_cindex", "std_cindex"]
            w = csv.DictWriter(f, fieldnames=fn)
            w.writeheader()
            for r in out_rows:
                w.writerow({
                    "day_name": r["day_name"],
                    "mean_cindex": f"{r['mean_cindex']:.6f}",
                    "max_cindex": f"{r['max_cindex']:.6f}",
                    "min_cindex": f"{r['min_cindex']:.6f}",
                    "std_cindex": f"{r['std_cindex']:.6f}",
                })

    def _variability_per_hour(self, days, hours, data, out_png, title_prefix=""):
        self._require_matplotlib()

        stds = []
        means = []
        for h in hours:
            vals = np.array([data[d][h]["cidx"] for d in days], dtype=float)
            means.append(float(vals.mean()))
            stds.append(float(vals.std()))

        x = np.arange(len(hours))
        plt.figure(figsize=(14, 5))
        plt.plot(x, means, marker="o", label="Mean")
        plt.plot(x, stds, marker="o", label="Std across days")
        plt.xticks(x, [str(h).zfill(2) for h in hours])
        plt.xlabel("Hour")
        plt.ylabel("Value")
        ttl = "Variability per Hour (Mean and Std of Cindex across days)"
        if title_prefix:
            ttl = f"{title_prefix} {ttl}"
        plt.title(ttl)
        plt.grid(True, axis="y", alpha=0.25)
        plt.legend(loc="upper right")
        plt.tight_layout()
        plt.savefig(out_png, dpi=150)
        plt.close()

    def _write_signature_table(self, days, hours, data, out_csv):
        # detailed table day hour with dominance and shares
        with open(out_csv, "w", encoding="utf-8", newline="") as f:
            fn = [
                "day_name", "hour",
                "free_km2", "moderate_km2", "heavy_km2", "severe_km2",
                "traffic_total_km2",
                "share_free", "share_moderate", "share_heavy", "share_severe",
                "dominant_class",
                "mean_cindex"
            ]
            w = csv.DictWriter(f, fieldnames=fn)
            w.writeheader()
            for d in days:
                for h in hours:
                    v = data[d][h]
                    tot = v["free"] + v["mod"] + v["heavy"] + v["sev"]
                    if tot > 0:
                        sf = v["free"] / tot
                        sm = v["mod"] / tot
                        sh = v["heavy"] / tot
                        ss = v["sev"] / tot
                    else:
                        sf = sm = sh = ss = 0.0
                    dom = self._dominant_class(v["free"], v["mod"], v["heavy"], v["sev"])
                    w.writerow({
                        "day_name": d,
                        "hour": str(h),
                        "free_km2": f"{v['free']:.6f}",
                        "moderate_km2": f"{v['mod']:.6f}",
                        "heavy_km2": f"{v['heavy']:.6f}",
                        "severe_km2": f"{v['sev']:.6f}",
                        "traffic_total_km2": f"{tot:.6f}",
                        "share_free": f"{sf:.6f}",
                        "share_moderate": f"{sm:.6f}",
                        "share_heavy": f"{sh:.6f}",
                        "share_severe": f"{ss:.6f}",
                        "dominant_class": dom,
                        "mean_cindex": f"{v['cidx']:.6f}"
                    })

    # -------------------------
    # Main
    # -------------------------

    def processAlgorithm(self, parameters, context, feedback):

        in_csv = self.parameterAsFile(parameters, self.IN_CSV, context)
        out_folder = self.parameterAsString(parameters, self.OUT_FOLDER, context)
        out_folder = self._ensure_folder(out_folder)

        make_gif = self.parameterAsBool(parameters, self.MAKE_GIF, context)
        gif_fps = float(self.parameterAsDouble(parameters, self.GIF_FPS, context))
        spf = float(self.parameterAsDouble(parameters, self.GIF_SECONDS_PER_FRAME, context))
        gif_name = (self.parameterAsString(parameters, self.GIF_NAME, context) or "06_animated_congestion_curve.gif").strip()

        k = int(self.parameterAsInt(parameters, self.CLUSTER_K, context))
        prom_frac = float(self.parameterAsDouble(parameters, self.PEAK_PROM_FRAC, context))

        title_prefix = (self.parameterAsString(parameters, self.TITLE_PREFIX, context) or "").strip()

        if not in_csv or (not os.path.exists(in_csv)):
            raise QgsProcessingException("Input CSV not found.")

        rows = self._read_csv(in_csv)
        if not rows:
            raise QgsProcessingException("CSV is empty or unreadable.")

        days, hours, data = self._pivot_day_hour(rows)
        if not days:
            raise QgsProcessingException("No day_name found in CSV.")
        if plt is None:
            raise QgsProcessingException("matplotlib is required for this toolbox. Please install matplotlib.")

        outputs = {}

        # 2 PNG dasar
        p_stacked = self._safe_path(out_folder, "hourly_traffic_area_stacked.png")
        p_line = self._safe_path(out_folder, "hourly_mean_congestion_index.png")
        self._plot_base_stacked_area(days, hours, data, p_stacked, title_prefix=title_prefix)
        self._plot_base_line_cindex(days, hours, data, p_line, title_prefix=title_prefix)
        outputs["BASE_STACKED_BAR_PNG"] = p_stacked
        outputs["BASE_LINE_PNG"] = p_line

        # 12 output lanjutan
        p01 = self._safe_path(out_folder, "01_heatmap_day_hour_cindex.png")
        self._plot_heatmap_day_hour(days, hours, data, p01, title_prefix=title_prefix)
        outputs["OUT_01_HEATMAP"] = p01

        p02 = self._safe_path(out_folder, "02_dominance_day_hour.png")
        self._plot_dominance_timeline(days, hours, data, p02, title_prefix=title_prefix)
        outputs["OUT_02_DOMINANCE"] = p02

        p03 = self._safe_path(out_folder, "03_congestion_phase_diagram.png")
        self._plot_phase_diagram(days, hours, data, p03, title_prefix=title_prefix)
        outputs["OUT_03_PHASE"] = p03

        p04 = self._safe_path(out_folder, "04_rush_hour_detector_plot.png")
        c04 = self._safe_path(out_folder, "04_rush_hour_detector.csv")
        self._rush_hour_detector(days, hours, data, p04, c04, prom_frac=prom_frac, title_prefix=title_prefix)
        outputs["OUT_04_RUSH_PLOT"] = p04
        outputs["OUT_04_RUSH_CSV"] = c04

        p05 = self._safe_path(out_folder, "05_temporal_clustering_heatmap.png")
        self._temporal_clustering_heatmap(days, hours, data, p05, k=k, title_prefix=title_prefix)
        outputs["OUT_05_CLUSTER"] = p05

        # 06 GIF
        gif_path = ""
        if make_gif:
            if imageio is None:
                feedback.pushWarning("imageio not available, skipping animated congestion curve GIF.")
            else:
                # Build a simpler GIF: one frame per hour for the mean curve only
                # More stable and lighter than per day per hour
                frame_paths = []
                x = np.arange(len(hours))
                y = np.array([float(np.mean([data[d][h]["cidx"] for d in days])) for h in hours], dtype=float)

                for j in range(len(hours)):
                    plt.figure(figsize=(10, 4))
                    plt.plot(x[:j+1], y[:j+1], marker="o")
                    plt.xlim(0, len(hours)-1)
                    ymin = float(y.min())
                    ymax = float(y.max())
                    pad = 0.05 * (ymax - ymin if ymax > ymin else 1.0)
                    plt.ylim(ymin - pad, ymax + pad)
                    plt.xticks(x, [str(h).zfill(2) for h in hours])
                    plt.xlabel("Hour")
                    plt.ylabel("Mean Congestion Index")
                    ttl = f"Animated Congestion Curve (Mean) up to {hours[j]:02d}:00"
                    if title_prefix:
                        ttl = f"{title_prefix} {ttl}"
                    plt.title(ttl)
                    plt.grid(True, axis="y", alpha=0.25)
                    plt.tight_layout()

                    frame = os.path.join(out_folder, f"__frame_mean_{hours[j]:02d}.png")
                    plt.savefig(frame, dpi=120)
                    plt.close()
                    frame_paths.append(frame)

                gif_path = os.path.join(out_folder, gif_name)
                self._write_gif(frame_paths, gif_path, gif_fps, (spf if spf > 0 else 0.0), feedback=feedback)

                for p in frame_paths:
                    try:
                        os.remove(p)
                    except Exception:
                        pass

        outputs["OUT_06_GIF"] = gif_path

        p07 = self._safe_path(out_folder, "07_radar_profile_per_day.png")
        self._radar_profile_per_day(days, hours, data, p07, title_prefix=title_prefix)
        outputs["OUT_07_RADAR"] = p07

        p08 = self._safe_path(out_folder, "08_peak_detection_labeled.png")
        self._peak_detection_week_timeline(rows, p08, prom_frac=prom_frac, title_prefix=title_prefix)
        outputs["OUT_08_PEAK_WEEK"] = p08

        p09 = self._safe_path(out_folder, "09_urban_traffic_signature_curve.png")
        self._urban_signature_curve(days, hours, data, p09, title_prefix=title_prefix)
        outputs["OUT_09_SIGNATURE"] = p09

        p10a = self._safe_path(out_folder, "10_weekday_vs_weekend_cindex.png")
        p10b = self._safe_path(out_folder, "10_weekday_vs_weekend_area.png")
        self._weekday_weekend_compare(days, hours, data, p10a, p10b, title_prefix=title_prefix)
        outputs["OUT_10_WDWE_CINDEX"] = p10a
        outputs["OUT_10_WDWE_AREA"] = p10b

        p11 = self._safe_path(out_folder, "11_signature_metrics_per_day.png")
        c11 = self._safe_path(out_folder, "11_signature_metrics_per_day.csv")
        self._signature_metrics_per_day(days, hours, data, p11, c11, title_prefix=title_prefix)
        outputs["OUT_11_METRICS_PNG"] = p11
        outputs["OUT_11_METRICS_CSV"] = c11

        p12 = self._safe_path(out_folder, "12_variability_per_hour.png")
        self._variability_per_hour(days, hours, data, p12, title_prefix=title_prefix)
        outputs["OUT_12_VARIABILITY"] = p12

        # signature table
        sig_csv = self._safe_path(out_folder, "traffic_signature_table.csv")
        self._write_signature_table(days, hours, data, sig_csv)
        outputs["SIGNATURE_TABLE_CSV"] = sig_csv

        # clickable link in QGIS log
        folder_url = QUrl.fromLocalFile(out_folder)
        feedback.pushInfo("Done. Outputs written to: " + out_folder)
        feedback.pushInfo("Open output folder: " + folder_url.toString())

        # optional: auto-open folder (only if you want it to open automatically)
        # QDesktopServices.openUrl(folder_url)


        return {
            "BASE_STACKED_BAR_PNG": outputs["BASE_STACKED_BAR_PNG"],
            "BASE_LINE_PNG": outputs["BASE_LINE_PNG"],
            "OUT_01_HEATMAP": outputs["OUT_01_HEATMAP"],
            "OUT_02_DOMINANCE": outputs["OUT_02_DOMINANCE"],
            "OUT_03_PHASE": outputs["OUT_03_PHASE"],
            "OUT_04_RUSH_PLOT": outputs["OUT_04_RUSH_PLOT"],
            "OUT_04_RUSH_CSV": outputs["OUT_04_RUSH_CSV"],
            "OUT_05_CLUSTER": outputs["OUT_05_CLUSTER"],
            "OUT_06_GIF": outputs["OUT_06_GIF"],
            "OUT_07_RADAR": outputs["OUT_07_RADAR"],
            "OUT_08_PEAK_WEEK": outputs["OUT_08_PEAK_WEEK"],
            "OUT_09_SIGNATURE": outputs["OUT_09_SIGNATURE"],
            "OUT_10_WDWE_CINDEX": outputs["OUT_10_WDWE_CINDEX"],
            "OUT_10_WDWE_AREA": outputs["OUT_10_WDWE_AREA"],
            "OUT_11_METRICS_PNG": outputs["OUT_11_METRICS_PNG"],
            "OUT_11_METRICS_CSV": outputs["OUT_11_METRICS_CSV"],
            "OUT_12_VARIABILITY": outputs["OUT_12_VARIABILITY"],
            "SIGNATURE_TABLE_CSV": outputs["SIGNATURE_TABLE_CSV"],
            "OUT_FOLDER": out_folder,
        }

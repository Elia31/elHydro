# src/api/routes_measurements.py
# REST-Endpunkte für Messdaten: liefert Messhistorie, Live-Daten und Excel/CSV-Export.
import io
import json
import os
from datetime import datetime
from typing import List
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from src.utils.constants import load_plant_presets, PRESETS_FILE, DEFAULT_IRR_DELTA

router = APIRouter()

# Wird in main.py gesetzt
data_manager = None


@router.get("/devices/{mac}/history")
def get_history(mac: str, limit: int = 200, from_ts: int = 0):
    dev = data_manager.get_device(mac)
    if not dev:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden")
    return data_manager.get_history(mac, limit=limit, from_ts=from_ts)


@router.get("/devices/{mac}/measurements")
def get_measurements(mac: str, limit: int = 100, offset: int = 0):
    dev = data_manager.get_device(mac)
    if not dev:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden")
    return data_manager.get_measurements_paginated(mac, limit=limit, offset=offset)


@router.get("/devices/{mac}/export/csv")
def export_csv(mac: str):
    dev = data_manager.get_device(mac)
    if not dev:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden")

    csv_path = data_manager.get_csv_path(mac)
    if not csv_path:
        raise HTTPException(status_code=404, detail="Keine Messdaten vorhanden")

    filename = f"elhydro_{mac.replace(':', '_')}_{datetime.now().strftime('%Y%m%d')}.csv"
    return FileResponse(
        csv_path,
        media_type="text/csv",
        filename=filename,
    )


@router.get("/devices/{mac}/export/excel")
def export_excel(mac: str):
    dev = data_manager.get_device(mac)
    if not dev:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden")

    history = data_manager.get_history(mac)
    if not history:
        raise HTTPException(status_code=404, detail="Keine Messdaten vorhanden")

    try:
        import openpyxl
        from openpyxl import Workbook
        from openpyxl.chart import LineChart, Reference
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise HTTPException(status_code=500, detail="openpyxl nicht installiert")

    wb = Workbook()

    # --- Sheet 1: Messdaten ---
    ws_data = wb.active
    ws_data.title = "Messdaten"

    headers = [
        "Mess-ID", "Zeitstempel", "Online",
        "Bodenfeuchte (%)", "Temperatur (°C)",
        "Luftfeuchte (%)", "Batterie (V)", "Ziel-Feuchte (%)",
        "Bewässert", "Bewässerungsdauer (ms)", "Ges. Bewässerung (ms)",
        "Brain Schlafzeit (s)", "Brain Bewässerung", "Brain Begründung",
        "Letzte Schlafdauer (s)",
    ]
    ws_data.append(headers)

    for row in history:
        ts = row.get("timestamp", 0)
        if isinstance(ts, (int, float)) and ts > 0:
            ts_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        else:
            ts_str = str(ts)

        brain_irr = row.get("brain_irrigate")
        if isinstance(brain_irr, str):
            brain_irr_str = "Ja" if brain_irr.lower() in ("true", "1") else "Nein"
        else:
            brain_irr_str = "Ja" if brain_irr else "Nein"

        ws_data.append([
            row.get("measurement_id"),
            ts_str,
            "Ja" if row.get("online") else "Nein",
            row.get("soil_pct"),
            row.get("temp"),
            row.get("rh"),
            row.get("vbat"),
            row.get("target_soil_pct"),
            "Ja" if row.get("irrigated") else "Nein",
            row.get("irrigation_ms", 0),
            row.get("total_irrigation_ms", 0),
            row.get("brain_sleep_s"),
            brain_irr_str,
            row.get("brain_reasoning", ""),
            row.get("last_sleep_duration_s", 0),
        ])

    # Spaltenbreiten
    for col_idx, header in enumerate(headers, 1):
        ws_data.column_dimensions[get_column_letter(col_idx)].width = max(len(header) + 2, 14)

    # --- Sheet 2: Diagramme (letzte 50 Messungen) ---
    chart_data = history[-50:]
    if len(chart_data) >= 2:
        from openpyxl.chart import BarChart
        from openpyxl.styles import Font, Alignment

        ws_chart = wb.create_sheet("Diagramme")

        # Überschrift
        ws_chart.append([f"Letzten {len(chart_data)} Messungen"])
        ws_chart.merge_cells("A1:H1")
        ws_chart["A1"].font = Font(bold=True, size=14)
        ws_chart["A1"].alignment = Alignment(horizontal="center")

        # Spalten: Nr. | Bodenfeuchte | Temperatur | Luftfeuchte | Ziel | Batterie | Bewässerung
        ws_chart.append([
            "Nr.", "Bodenfeuchte (%)", "Temperatur (°C)",
            "Luftfeuchte (%)", "Ziel (%)", "Batterie (V)",
            "Bewässerungsdauer (ms)",
            "Schlafdauer (h)",
        ])

        def _float(val, default=0):
            try:
                return float(val) if val is not None else default
            except (ValueError, TypeError):
                return default

        for i, row in enumerate(chart_data, 1):
            ws_chart.append([
                i,
                _float(row.get("soil_pct")),
                _float(row.get("temp")),
                _float(row.get("rh")),
                _float(row.get("target_soil_pct")),
                _float(row.get("vbat")),
                _float(row.get("irrigation_ms")),
                round(_float(row.get("last_sleep_duration_s")) / 3600, 1),
            ])

        num_rows = len(chart_data) + 2  # +2: Überschrift + Header
        cats = Reference(ws_chart, min_col=1, min_row=3, max_row=num_rows)

        # --- Chart 1: Bodenfeuchte + Bewässerung (Kombichart) ---
        chart1 = LineChart()
        chart1.title = "Bodenfeuchte & Bewässerung"
        chart1.y_axis.title = "Prozent (%)"
        chart1.x_axis.title = "Messung"
        chart1.height = 15
        chart1.width = 25

        soil_ref = Reference(ws_chart, min_col=2, min_row=2, max_row=num_rows)
        target_ref = Reference(ws_chart, min_col=5, min_row=2, max_row=num_rows)

        chart1.add_data(soil_ref, titles_from_data=True)
        chart1.add_data(target_ref, titles_from_data=True)
        chart1.set_categories(cats)

        # Styling: Bodenfeuchte grün, Ziel grau gestrichelt
        chart1.series[0].graphicalProperties.line.solidFill = "27AE60"
        chart1.series[0].graphicalProperties.line.width = 25000
        chart1.series[1].graphicalProperties.line.solidFill = "95A5A6"
        chart1.series[1].graphicalProperties.line.width = 20000
        chart1.series[1].graphicalProperties.line.dashStyle = "dash"

        chart1.y_axis.numFmt = '0'
        chart1.y_axis.delete = False
        chart1.x_axis.delete = False
        chart1.x_axis.tickLblPos = "low"

        # Balken: Bewässerungsdauer (rechte Y-Achse, ms)
        bar_chart = BarChart()
        bar_chart.title = None
        bar_ref = Reference(ws_chart, min_col=7, min_row=2, max_row=num_rows)
        bar_chart.add_data(bar_ref, titles_from_data=True)
        bar_chart.set_categories(cats)
        bar_chart.y_axis.axId = 200
        bar_chart.y_axis.delete = False
        bar_chart.series[0].graphicalProperties.solidFill = "3498DB"

        chart1.y_axis.crosses = "min"
        chart1 += bar_chart

        ws_chart.add_chart(chart1, "I3")

        # --- Chart 2: Temperatur + Luftfeuchte ---
        chart2 = LineChart()
        chart2.title = "Temperatur & Luftfeuchte"
        chart2.y_axis.title = "°C / %"
        chart2.x_axis.title = "Messung"
        chart2.height = 15
        chart2.width = 25

        temp_ref = Reference(ws_chart, min_col=3, min_row=2, max_row=num_rows)
        rh_ref = Reference(ws_chart, min_col=4, min_row=2, max_row=num_rows)

        chart2.add_data(temp_ref, titles_from_data=True)
        chart2.add_data(rh_ref, titles_from_data=True)
        chart2.set_categories(cats)

        # Styling: Temperatur orange, Luftfeuchte blau
        chart2.series[0].graphicalProperties.line.solidFill = "E67E22"
        chart2.series[0].graphicalProperties.line.width = 22000
        chart2.series[1].graphicalProperties.line.solidFill = "3498DB"
        chart2.series[1].graphicalProperties.line.width = 22000

        chart2.y_axis.numFmt = '0.0'
        chart2.y_axis.delete = False
        chart2.x_axis.delete = False
        chart2.x_axis.tickLblPos = "low"

        ws_chart.add_chart(chart2, "Y3")

        # --- Chart 3: Batterie (Balkendiagramm) ---
        chart3 = BarChart()
        chart3.type = "col"
        chart3.title = "Batteriespannung (V)"
        chart3.y_axis.title = None
        chart3.x_axis.title = "Messung"
        chart3.height = 15
        chart3.width = 25
        chart3.legend = None

        vbat_ref = Reference(ws_chart, min_col=6, min_row=2, max_row=num_rows)
        chart3.add_data(vbat_ref, titles_from_data=True)
        chart3.set_categories(cats)

        # Styling: rote Balken
        chart3.series[0].graphicalProperties.solidFill = "27AE60"

        # Y-Achse: Bereich an Daten anpassen (nicht bei 0 starten)
        vbat_values = [_float(row.get("vbat")) for row in chart_data if _float(row.get("vbat")) > 0]
        if vbat_values:
            vbat_min = min(vbat_values)
            vbat_max = max(vbat_values)
            margin = (vbat_max - vbat_min) * 0.15 or 0.05
            chart3.y_axis.scaling.min = round(vbat_min - margin, 2)
            chart3.y_axis.scaling.max = round(vbat_max + margin, 2)
        chart3.y_axis.numFmt = '0.00'
        chart3.y_axis.delete = False
        chart3.x_axis.delete = False
        chart3.x_axis.tickLblPos = "low"

        ws_chart.add_chart(chart3, "I36")

        # --- Chart 4: Schlafdauer (Balkendiagramm) ---
        chart4 = BarChart()
        chart4.type = "col"
        chart4.title = "Schlafdauer pro Messung"
        chart4.y_axis.title = "Stunden (h)"
        chart4.x_axis.title = "Messung"
        chart4.height = 15
        chart4.width = 25
        chart4.legend = None

        sleep_ref = Reference(ws_chart, min_col=8, min_row=2, max_row=num_rows)
        chart4.add_data(sleep_ref, titles_from_data=True)
        chart4.set_categories(cats)

        chart4.series[0].graphicalProperties.solidFill = "9B59B6"

        chart4.y_axis.numFmt = '0.0'
        chart4.y_axis.delete = False
        chart4.x_axis.delete = False
        chart4.x_axis.tickLblPos = "low"

        ws_chart.add_chart(chart4, "Y36")

    # In Buffer schreiben
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    filename = f"elhydro_{mac.replace(':', '_')}_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/plant-presets")
def get_plant_presets():
    return load_plant_presets()


class PresetModel(BaseModel):
    id: str
    name: str
    target_soil_pct: int
    sleep_multiplier: float
    irrigation_start_delta: int = DEFAULT_IRR_DELTA


@router.put("/plant-presets")
def save_plant_presets(presets: List[PresetModel]):
    """Speichert die gesamte Preset-Liste."""
    data = [p.model_dump() for p in presets]
    with open(PRESETS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    return {"status": "ok", "count": len(data)}

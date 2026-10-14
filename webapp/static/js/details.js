// details.js - Geräte-Details mit Charts und Diagnose

const Details = {
    container: null,
    mac: null,
    chart: null,
    lastHistory: null,
    lastTarget: 50,
    activeSeries: new Set(["soil_pct", "temp", "irrigation_ms"]),
    messdatenLoaded: false,
    messdatenOffset: 0,
    messdatenTotal: 0,
    messdatenPageSize: 100,
    messdatenShowExtended: false,

    async render(el, mac) {
        this.container = el;
        this.mac = mac;
        this.messdatenLoaded = false;
        this.messdatenOffset = 0;
        this.messdatenShowExtended = false;

        el.innerHTML = `<div class="loading"><div class="loader"><span></span><span></span><span></span></div></div>`;

        try {
            const [device, history] = await Promise.all([
                App.api(`/devices/${encodeURIComponent(mac)}`),
                // Gleiche Abfrage wie der beim Öffnen markierte Button "Max"
                App.api(`/devices/${encodeURIComponent(mac)}/history?limit=50000`),
            ]);

            const name = device.name || mac;
            const typeIconId = device.type === "outdoor" ? "icon-sun" : "icon-home";
            const lastM = history.length > 0 ? history[history.length - 1] : {};
            const soilPct = lastM.soil_pct ?? 0;
            const target = device.config?.target_soil_pct ?? 50;
            const lastIrrigatedTs = device.last_irrigated_ts
                || history.findLast(r => r.irrigated === true || r.irrigated === 'True' || r.irrigated === '1')?.timestamp
                || 0;

            el.innerHTML = `
                <div class="page-enter">
                    <div class="page-header">
                        <div>
                            <h1 class="page-title">
                                <svg><use href="#${typeIconId}"/></svg>
                                ${this.esc(name)}
                            </h1>
                            <div class="page-subtitle">${mac}</div>
                        </div>
                        <div style="display:flex;gap:0.5rem;flex-wrap:wrap">
                            <button class="btn btn-outline btn-sm" onclick="App.navigate('/')">
                                <svg width="14" height="14"><use href="#icon-arrow-left"/></svg>
                                Zurück
                            </button>
                            <button class="btn btn-outline btn-sm" onclick="App.navigate('/settings/${encodeURIComponent(mac)}')">
                                <svg width="14" height="14"><use href="#icon-settings"/></svg>
                                Einstellungen
                            </button>
                        </div>
                    </div>

                    <!-- Hero: Gauge + Stats 3-Column -->
                    <div class="details-hero">
                        <div class="details-hero-gauge">
                            <div class="gauge-wrapper">
                                <div class="gauge-fill" id="gauge-fill" style="background: conic-gradient(${this.gaugeColor(soilPct, target)} ${soilPct * 3.6}deg, var(--border) ${soilPct * 3.6}deg);">
                                    <div class="gauge-inner">
                                        <div class="gauge-value" id="gauge-value">${soilPct}%</div>
                                    </div>
                                </div>
                            </div>
                            <div class="gauge-status" id="gauge-status">
                                <span style="color:${this.gaugeColor(soilPct, target)}">${this.gaugeStatusText(soilPct, target)}</span>
                                <span class="gauge-target-label">Ziel: ${target}%</span>
                            </div>
                        </div>
                        <div class="details-hero-stats" id="live-stats">
                            ${this.liveStatsHtml(lastM, device, lastIrrigatedTs)}
                        </div>
                    </div>

                    <!-- Tabs -->
                    <div class="tabs">
                        <button class="tab active" onclick="Details.switchTab('overview')">Übersicht</button>
                        <button class="tab" onclick="Details.switchTab('diagnostics')">Diagnostik</button>
                        <button class="tab" onclick="Details.switchTab('messdaten')">Messdaten</button>
                    </div>

                    <div class="tab-content active" id="tab-overview">
                        <!-- Insight: Weather + Brain -->
                        <div class="insight-grid" id="insight-cards">
                            ${this.weatherCardHtml(device)}
                            ${this.brainCardHtml(lastM, device)}
                        </div>

                        <div class="chart-container">
                            <div class="chart-range-btns" id="chart-range-btns">
                                <button class="btn btn-outline btn-sm" onclick="Details.loadRange('24h', event)">24h</button>
                                <button class="btn btn-outline btn-sm" onclick="Details.loadRange('7d', event)">7 Tage</button>
                                <button class="btn btn-outline btn-sm" onclick="Details.loadRange('30d', event)">30 Tage</button>
                                <button class="btn btn-outline btn-sm active" onclick="Details.loadRange('max', event)">Max</button>
                            </div>
                            <div class="chart-series-btns" id="chart-series-btns">
                                <button class="btn btn-outline btn-sm series-btn active" data-series="soil_pct" onclick="Details.toggleSeries('soil_pct', this)" style="--series-color:var(--primary)">Bodenfeuchte</button>
                                <button class="btn btn-outline btn-sm series-btn active" data-series="temp" onclick="Details.toggleSeries('temp', this)" style="--series-color:var(--warning)">Temperatur</button>
                                <button class="btn btn-outline btn-sm series-btn" data-series="rh" onclick="Details.toggleSeries('rh', this)" style="--series-color:var(--info)">Luftfeuchte</button>
                                <button class="btn btn-outline btn-sm series-btn" data-series="vbat" onclick="Details.toggleSeries('vbat', this)" style="--series-color:#22c55e">Batterie</button>
                                <button class="btn btn-outline btn-sm series-btn active" data-series="irrigation_ms" onclick="Details.toggleSeries('irrigation_ms', this)" style="--series-color:#3b82f6">Bewässerung</button>
                            </div>
                            <div class="chart-canvas-wrapper"><canvas id="soil-chart"></canvas></div>
                        </div>
                        <div class="card notes-card" style="padding:1.25rem;margin-top:1.5rem">
                            <div class="brain-card-title">
                                <svg><use href="#icon-info"/></svg>
                                Notizen
                            </div>
                            <textarea id="device-notes" class="form-textarea" rows="3"
                                placeholder="Notizen zu dieser Pflanze..."
                                onblur="Details.saveNotes()">${this.esc(device.notes || '')}</textarea>
                        </div>
                        <div class="export-btns">
                            <a href="/api/devices/${encodeURIComponent(mac)}/export/csv"
                               class="btn btn-outline btn-sm" download>
                                <svg width="14" height="14"><use href="#icon-download"/></svg>
                                CSV
                            </a>
                            <a href="/api/devices/${encodeURIComponent(mac)}/export/excel"
                               class="btn btn-outline btn-sm" download>
                                <svg width="14" height="14"><use href="#icon-download"/></svg>
                                Excel
                            </a>
                        </div>
                    </div>

                    <div class="tab-content" id="tab-diagnostics">
                        <div class="diag-cards-grid" id="diag-stats">
                            ${this.diagCardsHtml(lastM)}
                        </div>
                    </div>

                    <div class="tab-content" id="tab-messdaten">
                        <div class="messdaten-toolbar">
                            <div class="messdaten-info" id="messdaten-info"></div>
                            <div style="display:flex;gap:0.5rem;align-items:center;flex-wrap:wrap">
                                <button class="btn btn-outline btn-sm" id="messdaten-toggle-cols" onclick="Details.toggleExtendedCols()">
                                    <svg width="14" height="14"><use href="#icon-settings"/></svg>
                                    Alle Felder
                                </button>
                                <a href="/api/devices/${encodeURIComponent(mac)}/export/csv"
                                   class="btn btn-outline btn-sm" download>
                                    <svg width="14" height="14"><use href="#icon-download"/></svg>
                                    CSV
                                </a>
                                <a href="/api/devices/${encodeURIComponent(mac)}/export/excel"
                                   class="btn btn-outline btn-sm" download>
                                    <svg width="14" height="14"><use href="#icon-download"/></svg>
                                    Excel
                                </a>
                            </div>
                        </div>
                        <div class="messdaten-table-wrapper" id="messdaten-table-wrapper">
                            <div class="loading"><div class="loader"><span></span><span></span><span></span></div></div>
                        </div>
                        <div class="messdaten-pagination" id="messdaten-pagination"></div>
                    </div>

                    <div style="margin-top:2.5rem">
                        <button class="btn btn-danger btn-sm" onclick="Details.deleteDevice()">
                            <svg width="14" height="14"><use href="#icon-trash"/></svg>
                            Gerät löschen
                        </button>
                    </div>
                </div>
            `;

            this.renderChart(history, target);
        } catch (e) {
            el.innerHTML = `<p style="color:var(--danger)">Fehler: ${e.message}</p>
                <a href="/" class="btn btn-outline btn-sm" style="margin-top:1rem" onclick="return App.link(event)">
                    <svg width="14" height="14"><use href="#icon-arrow-left"/></svg>
                    Zurück
                </a>`;
        }
    },

    gaugeColor(pct, target) {
        const diff = pct - target;
        if (diff < -10) return 'var(--danger)';
        if (diff < -5) return 'var(--warning)';
        if (diff > 20) return 'var(--info)';
        return 'var(--primary)';
    },

    gaugeStatusText(pct, target) {
        const diff = pct - target;
        if (diff < -10) return 'Zu trocken';
        if (diff < -5) return 'Trocken';
        if (diff > 20) return 'Zu nass';
        return 'Optimal';
    },

    liveStatsHtml(m, device, irrigatedTs) {
        const target = device?.config?.target_soil_pct ?? 50;
        const lastSeen = device?.last_seen;
        const lastIrrigatedTs = irrigatedTs ?? device?.last_irrigated_ts ?? 0;
        return `
            <div class="stat-item accent-teal">
                <div class="stat-icon-circle teal"><svg><use href="#icon-droplet"/></svg></div>
                <div>
                    <div class="stat-label">ADC Soil Raw</div>
                    <div class="stat-value">${m.soil_raw ?? '-'}</div>
                    <div class="stat-sub">Dry: ${m.calib_dry ?? '-'} / Wet: ${m.calib_wet ?? '-'}</div>
                </div>
            </div>
            <div class="stat-item accent-yellow">
                <div class="stat-icon-circle amber"><svg><use href="#icon-thermometer"/></svg></div>
                <div>
                    <div class="stat-label">Temperatur</div>
                    <div class="stat-value">${m.temp != null ? Number(m.temp).toFixed(1) + '°C' : '-'}</div>
                </div>
            </div>
            <div class="stat-item accent-blue">
                <div class="stat-icon-circle blue"><svg><use href="#icon-humidity"/></svg></div>
                <div>
                    <div class="stat-label">Luftfeuchte</div>
                    <div class="stat-value">${m.rh != null ? Number(m.rh).toFixed(0) + '%' : '-'}</div>
                </div>
            </div>
            <div class="stat-item accent-green">
                <div class="stat-icon-circle green"><svg><use href="#icon-battery"/></svg></div>
                <div>
                    <div class="stat-label">Batterie</div>
                    <div class="stat-value">${m.vbat ? (Math.round(m.vbat * 100) / 100).toFixed(2) + ' V' : '-'}</div>
                    ${m.vbat ? `<div class="stat-sub">~${App.batteryPercent(Math.round(m.vbat * 100) / 100)}%</div>` : ''}
                </div>
            </div>
            <div class="stat-item accent-purple">
                <div class="stat-icon-circle purple"><svg><use href="#icon-clock"/></svg></div>
                <div>
                    <div class="stat-label">Zuletzt gesehen</div>
                    <div class="stat-value" style="font-size:1.1rem">${lastSeen ? App.timeAgo(lastSeen) : '-'}</div>
                    ${lastSeen ? `<div class="stat-sub">${App.formatTimestamp(lastSeen)}</div>` : ''}
                </div>
            </div>
            <div class="stat-item accent-blue">
                <div class="stat-icon-circle blue"><svg><use href="#icon-droplet"/></svg></div>
                <div>
                    <div class="stat-label">Letzte Bewässerung</div>
                    <div class="stat-value" style="font-size:1.1rem">${lastIrrigatedTs ? App.timeAgo(lastIrrigatedTs) : 'Nie'}</div>
                    ${lastIrrigatedTs ? `<div class="stat-sub">${App.formatTimestamp(lastIrrigatedTs)}</div>` : ''}
                </div>
            </div>
        `;
    },

    diagCardsHtml(m) {
        const items = [
            { label: 'Mess-Nr.', value: m.measurement_id ?? '-', sub: 'Fortlaufende Messung' },
            { label: 'Rohwert Boden', value: m.soil_raw ?? '-', sub: 'ADC-Wert Sensor' },
            { label: 'Reset-Grund', value: m.reset_reason != null ? App.resetReasonText(m.reset_reason) : '-', sub: 'Letzter Neustart' },
            { label: 'Freier Speicher', value: m.free_heap_bytes ? (m.free_heap_bytes / 1024).toFixed(0) + ' KB' : '-', sub: 'Heap RAM' },
            { label: 'Wachzeit Gesamt', value: m.total_awake_ms != null ? App.formatDuration(m.total_awake_ms / 1000) : '-', sub: 'NVS-persistiert' },
            { label: 'Uptime', value: App.formatDuration(m.uptime_seconds), sub: 'Seit letztem Powercycle' },
            { label: 'Aufwach-Zyklen', value: m.total_wakeups ?? '-', sub: 'NVS-persistiert' },
            { label: 'BLE Erfolg', value: m.ble_success_pct != null ? m.ble_success_pct + '%' : '-', sub: 'Verbindungsrate' },
            { label: 'Bewässerung Total', value: m.total_irrigation_ms != null ? (m.total_irrigation_ms / 1000).toFixed(0) + 's' : '-', sub: 'Gesamte Pumplaufzeit' },
            { label: 'Kalibrierung Trocken', value: m.calib_dry ?? '-', sub: 'ADC bei 0% Feuchte' },
            { label: 'Kalibrierung Nass', value: m.calib_wet ?? '-', sub: 'ADC bei 100% Feuchte' },
            { label: 'Geplanter Schlaf', value: App.formatDuration(m.last_sleep_duration_s), sub: 'Geplante Schlafzeit (NVS)' },
            { label: 'Ø Wachzeit', value: m.avg_awake_s != null ? Number(m.avg_awake_s).toFixed(1) + 's' : '-', sub: 'Pro Aufwach-Zyklus' },
        ];

        return items.map(it => `
            <div class="stat-item">
                <div>
                    <div class="stat-label">${it.label}</div>
                    <div class="stat-value" style="font-size:1.1rem">${it.value}</div>
                    <div class="stat-sub">${it.sub}</div>
                </div>
            </div>
        `).join('');
    },

    SERIES_CONFIG: {
        soil_pct:      { label: "Bodenfeuchte (%)", key: "soil_pct", yAxisID: "y", fill: true, unit: "%" },
        temp:          { label: "Temperatur (°C)", key: "temp", yAxisID: "y1", fill: false, unit: "°C" },
        rh:            { label: "Luftfeuchte (%)", key: "rh", yAxisID: "y", fill: false, unit: "%" },
        vbat:          { label: "Batterie (V)", key: "vbat", yAxisID: "y2", fill: false, unit: "V" },
        irrigation_ms: { label: "Bewässerung", key: "irrigation_ms", yAxisID: "yIrr", fill: false, unit: "s", type: "bar" },
    },

    toggleSeries(seriesKey, btn) {
        if (this.activeSeries.has(seriesKey)) {
            if (this.activeSeries.size <= 1) return; // Mindestens eine Serie aktiv
            this.activeSeries.delete(seriesKey);
            btn.classList.remove("active");
        } else {
            this.activeSeries.add(seriesKey);
            btn.classList.add("active");
        }
        if (this.lastHistory) {
            this.renderChart(this.lastHistory, this.lastTarget);
        }
    },

    renderChart(history, target) {
        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }

        this.lastHistory = history;
        this.lastTarget = target;

        const canvas = document.getElementById("soil-chart");
        if (!canvas) return;

        const wrapper = canvas.parentElement;
        // Vorhandene Leer-Meldung entfernen
        const existingMsg = wrapper.querySelector('.chart-empty');
        if (existingMsg) existingMsg.remove();

        if (history.length === 0) {
            canvas.style.display = 'none';
            const msg = document.createElement('div');
            msg.className = 'chart-empty';
            msg.innerHTML = '<svg width="20" height="20" style="opacity:0.4"><use href="#icon-info"/></svg> Keine Messdaten in diesem Zeitraum';
            wrapper.appendChild(msg);
            return;
        }
        canvas.style.display = '';

        const labels = history.map(r => {
            const ts = r.timestamp;
            if (!ts) return `#${r.measurement_id} (Zeit unbekannt)`;
            const d = new Date(ts * 1000);
            return d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" })
                + " " + d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
        });

        const isDark = document.documentElement.getAttribute("data-theme") === "dark";
        const gridColor = isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.06)";
        const textColor = isDark ? "#94a3b8" : "#64748b";
        const primaryColor = isDark ? "#34d399" : "#059669";
        const dangerColor = isDark ? "#f87171" : "#dc2626";
        const warmColor = isDark ? "#fbbf24" : "#d97706";
        const infoColor = isDark ? "#38bdf8" : "#0284c7";
        const successColor = isDark ? "#4ade80" : "#16a34a";
        const fontCfg = { family: "'Inter', sans-serif", size: 11 };

        const irrigationColor = isDark ? "rgba(59, 130, 246, 0.5)" : "rgba(59, 130, 246, 0.4)";
        const seriesColors = {
            soil_pct: primaryColor,
            temp: warmColor,
            rh: infoColor,
            vbat: successColor,
            irrigation_ms: irrigationColor,
        };

        const isMobile = window.innerWidth < 600;
        const ctx = canvas.getContext("2d");
        const datasets = [];
        const scales = {
            x: {
                ticks: { color: textColor, maxRotation: isMobile ? 35 : 45, maxTicksLimit: isMobile ? 6 : 12, font: { family: "'Inter', sans-serif", size: isMobile ? 9 : 11 } },
                grid: { color: gridColor },
            },
        };

        // Dynamisch Datasets und Achsen aufbauen
        for (const seriesKey of this.activeSeries) {
            const cfg = this.SERIES_CONFIG[seriesKey];
            if (!cfg) continue;

            const color = seriesColors[seriesKey];
            const isBar = cfg.type === "bar";
            const data = isBar
                ? history.map(r => (r.irrigated === true || r.irrigated === 'True' || r.irrigated === '1')
                    ? ((Number(r.irrigation_ms) || 0) / 1000) : null)
                : history.map(r => r[cfg.key]);
            const ds = {
                label: cfg.label,
                data,
                borderColor: color,
                borderWidth: isBar ? 0 : (seriesKey === "soil_pct" ? 2.5 : 1.5),
                tension: isBar ? 0 : 0.4,
                fill: false,
                yAxisID: cfg.yAxisID,
            };
            if (isBar) {
                ds.type = "bar";
                ds.backgroundColor = color;
                ds.barThickness = 6;
                ds.borderRadius = 2;
                ds.order = 0; // bars behind lines
            }

            if (seriesKey === "soil_pct") {
                const gradient = ctx.createLinearGradient(0, 0, 0, canvas.parentElement.clientHeight || 300);
                gradient.addColorStop(0, isDark ? "rgba(52, 211, 153, 0.25)" : "rgba(5, 150, 105, 0.2)");
                gradient.addColorStop(1, isDark ? "rgba(52, 211, 153, 0.02)" : "rgba(5, 150, 105, 0.01)");
                ds.backgroundColor = gradient;
                ds.fill = true;
                ds.pointRadius = history.map(r =>
                    r.online === false || r.online === "False" || r.online === "false" || r.online === 0
                        ? 5 : (history.length > 50 ? 0 : 3)
                );
                ds.pointBackgroundColor = history.map(r =>
                    r.online === false || r.online === "False" || r.online === "false" || r.online === 0
                        ? dangerColor : primaryColor
                );
            } else {
                ds.pointRadius = 0;
            }

            datasets.push(ds);
        }

        // Zielwert-Linie nur wenn Bodenfeuchte aktiv
        if (this.activeSeries.has("soil_pct")) {
            datasets.push({
                label: "Zielwert (%)",
                data: history.map(r => r.target_soil_pct || target),
                borderColor: dangerColor,
                borderDash: [6, 4],
                borderWidth: 1.5,
                pointRadius: 0,
                fill: false,
                stepped: "before",
                yAxisID: "y",
            });
        }

        // Y-Achsen nur wenn zugehörige Serie aktiv
        const needsY = this.activeSeries.has("soil_pct") || this.activeSeries.has("rh");
        const needsY1 = this.activeSeries.has("temp");
        const needsY2 = this.activeSeries.has("vbat");
        const needsYIrr = this.activeSeries.has("irrigation_ms");

        const tickFont = { family: "'Inter', sans-serif", size: isMobile ? 9 : 11 };

        if (needsY) {
            scales.y = {
                min: 0, max: 100,
                title: { display: !isMobile, text: this.activeSeries.has("soil_pct") ? "%" : "%", color: textColor, font: { family: "'Inter', sans-serif", size: 11 } },
                ticks: { color: textColor, font: tickFont, maxTicksLimit: isMobile ? 6 : 10 },
                grid: { color: gridColor },
            };
        }
        if (needsY1) {
            scales.y1 = {
                position: "right",
                title: { display: !isMobile, text: "°C", color: textColor, font: { family: "'Inter', sans-serif", size: 11 } },
                ticks: { color: textColor, font: tickFont },
                grid: { display: false },
            };
        }
        if (needsY2) {
            scales.y2 = {
                position: "right",
                min: 2.5, max: 4.5,
                title: { display: !isMobile, text: "V", color: textColor, font: { family: "'Inter', sans-serif", size: 11 } },
                ticks: { color: textColor, font: tickFont },
                grid: { display: false },
            };
        }
        if (needsYIrr) {
            scales.yIrr = {
                display: false,
                min: 0,
            };
        }

        this.chart = new Chart(canvas, {
            type: "line",
            data: { labels, datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                hover: { mode: "index", intersect: false },
                plugins: {
                    legend: {
                        labels: {
                            color: textColor,
                            usePointStyle: true,
                            padding: isMobile ? 8 : 16,
                            boxWidth: isMobile ? 8 : 12,
                            font: { family: "'Inter', sans-serif", size: isMobile ? 10 : 12 },
                        },
                    },
                    tooltip: {
                        backgroundColor: isDark ? 'rgba(30, 41, 59, 0.92)' : 'rgba(255, 255, 255, 0.92)',
                        titleColor: isDark ? '#e2e8f0' : '#1e293b',
                        bodyColor: isDark ? '#94a3b8' : '#64748b',
                        borderColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)',
                        borderWidth: 1,
                        cornerRadius: 12,
                        padding: 12,
                        boxPadding: 4,
                        titleFont: { family: "'Inter', sans-serif", weight: '600', size: 13 },
                        bodyFont: { family: "'Inter', sans-serif", size: 12 },
                        callbacks: {
                            label: function(context) {
                                if (context.dataset.label === 'Bewässerung') {
                                    if (context.raw == null) return null;
                                    return `Bewässerung: ${context.raw.toFixed(1)}s`;
                                }
                                return `${context.dataset.label}: ${context.formattedValue}`;
                            },
                        },
                    },
                },
                scales,
            },
        });
    },

    weatherCodeIcon(code) {
        if (code <= 0) return "icon-sun";
        if (code <= 3) return "icon-cloud";
        if (code >= 61 && code <= 67) return "icon-cloud-rain";
        if (code >= 80 && code <= 82) return "icon-cloud-rain";
        if (code >= 71 && code <= 77) return "icon-cloud";
        return "icon-cloud";
    },

    weatherCodeText(code) {
        const map = {
            0: "Klar", 1: "Überwiegend klar", 2: "Teilweise bewölkt", 3: "Bewölkt",
            45: "Nebel", 48: "Nebel (Reif)", 51: "Leichter Nieselregen", 53: "Nieselregen",
            55: "Starker Nieselregen", 61: "Leichter Regen", 63: "Regen", 65: "Starker Regen",
            71: "Leichter Schnee", 73: "Schnee", 75: "Starker Schnee",
            80: "Regenschauer", 81: "Schauer", 82: "Starke Schauer",
            95: "Gewitter", 96: "Gewitter mit Hagel",
        };
        return map[code] || `Code ${code}`;
    },

    weatherCardHtml(device) {
        if (device.type !== "outdoor" || !device.last_weather) return "";
        const w = device.last_weather;
        const loc = device.location;
        let locLabel = "";
        if (typeof loc === "string" && loc.trim()) {
            locLabel = loc.trim();
        } else if (loc && typeof loc === "object" && loc.lat != null && loc.lon != null) {
            locLabel = `${Number(loc.lat).toFixed(2)}, ${Number(loc.lon).toFixed(2)}`;
        }
        return `
            <div class="card weather-card" style="padding:1.25rem;margin-bottom:1rem">
                <div class="brain-card-title">
                    <svg><use href="#${this.weatherCodeIcon(w.weather_code)}"/></svg>
                    Wetter - ${this.weatherCodeText(w.weather_code)}${locLabel ? ` · ${this.esc(locLabel)}` : ""}
                </div>
                <div class="stats-grid" style="grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); margin-top:0.5rem">
                    <div>
                        <span class="stat-label">Temperatur</span>
                        <div class="stat-value" style="font-size:1.1rem">${w.temperature != null ? w.temperature + '°C' : '-'}</div>
                    </div>
                    <div>
                        <span class="stat-label">Luftfeuchte</span>
                        <div class="stat-value" style="font-size:1.1rem">${w.humidity != null ? w.humidity + '%' : '-'}</div>
                    </div>
                    <div>
                        <span class="stat-label">Regen aktuell</span>
                        <div class="stat-value" style="font-size:1.1rem">${w.precipitation_now ?? 0} mm</div>
                    </div>
                    <div>
                        <span class="stat-label">Regen 1h</span>
                        <div class="stat-value" style="font-size:1.1rem">${w.precipitation_next_1h ?? 0} mm</div>
                    </div>
                    <div>
                        <span class="stat-label">Regen 3h</span>
                        <div class="stat-value" style="font-size:1.1rem">${w.precipitation_next_3h ?? 0} mm</div>
                    </div>
                    <div>
                        <span class="stat-label">Wind</span>
                        <div class="stat-value" style="font-size:1.1rem">${w.wind_speed ?? 0} km/h</div>
                    </div>
                </div>
                <div style="color:var(--text-muted);font-size:0.72rem;margin-top:0.5rem">
                    Aktualisiert: ${w.fetched_at ? App.timeAgo(w.fetched_at) : '-'}
                </div>
            </div>`;
    },

    brainCardHtml(m, device) {
        const sleepS = m.brain_sleep_s;
        const irrigate = m.brain_irrigate;
        const reasoning = m.brain_reasoning || '';
        const alerts = [...(m.alerts || [])];
        const nextWake = device?.next_wake_ts;
        if (device?.pump_dry) {
            alerts.unshift({ message: "Letzte Bewässerung ohne Wirkung: Pumpe fördert kein Wasser, Tank prüfen" });
        }

        const alertsHtml = alerts.length > 0
            ? `<div style="margin-top:0.75rem">${alerts.map(a =>
                `<div class="brain-alert-item"><svg><use href="#icon-alert-triangle"/></svg>${this.esc(a.message || a)}</div>`
              ).join('')}</div>`
            : '';

        if (!sleepS && !reasoning) {
            return `<div class="card brain-card-wrapper" style="padding:1.25rem;opacity:0.6">
                <div class="brain-card-title">
                    <svg><use href="#icon-brain"/></svg>
                    Letzte Brain-Entscheidung
                </div>
                <div style="color:var(--text-muted);font-size:0.9rem">Noch keine Entscheidung</div>
                ${alertsHtml}
            </div>`;
        }

        const didIrrigate = irrigate === true || irrigate === "True" || irrigate === "true";

        // Schwelle ohne Verdunstungszuschlag (gleiche Formel wie Firmware). Das
        // Vergleichszeichen kommt aus den Werten: Bei Hitze wird auch knapp darüber
        // gegossen, bei Frost, Cooldown oder Regen trotz Unterschreitung nicht.
        const target = m.target_soil_pct;
        const delta = m.irrigation_start_delta;
        let thresholdLabel = '';
        if (target != null && delta != null && m.soil_pct != null) {
            const threshold = App.soilThreshold(target, delta);
            const soil = m.soil_pct;
            thresholdLabel = `Boden ${soil}% ${soil < threshold ? '<' : '≥'} Schwelle ${threshold}%`;
        }

        const reasonParts = typeof reasoning === 'string'
            ? reasoning.split(/[;\n]/).filter(r => r.trim().length > 0).map(r => r.trim())
            : Array.isArray(reasoning) ? reasoning : [];

        const reasonHtml = reasonParts.length > 0
            ? `<div class="brain-reasoning-list">
                <div class="brain-reasoning-label">Begründung</div>
                ${reasonParts.map(r => `<div class="brain-reason-bullet"><span class="dot">•</span><span>${this.esc(r)}</span></div>`).join('')}
               </div>`
            : '';

        const nextWakeHtml = nextWake
            ? `<div class="brain-stat-box" style="grid-column:1/-1">
                <svg style="color:var(--secondary)"><use href="#icon-zap"/></svg>
                <div class="brain-stat-value">${App.formatTimestamp(nextWake)}</div>
                <div class="brain-stat-label">Nächste Messung · ${App.timeUntil(nextWake)}</div>
               </div>`
            : '';

        return `<div class="card brain-card-wrapper" style="padding:1.25rem">
            <div class="brain-card-title">
                <svg><use href="#icon-brain"/></svg>
                Letzte Brain-Entscheidung
            </div>
            <div class="brain-card-body">
                <div class="brain-stat-box">
                    <svg style="color:var(--primary)"><use href="#icon-clock"/></svg>
                    <div class="brain-stat-value">${App.formatDuration(sleepS)}</div>
                    <div class="brain-stat-label">Nächste Sleep Dauer</div>
                </div>
                <div class="brain-stat-box">
                    <svg style="color:${didIrrigate ? 'var(--info)' : 'var(--text-muted)'}"><use href="#icon-droplet"/></svg>
                    <div class="brain-stat-value">${didIrrigate ? 'Ja' : 'Nein'}</div>
                    <div class="brain-stat-label">Bewässerung${thresholdLabel ? ' · ' + thresholdLabel : ''}</div>
                </div>
                ${nextWakeHtml}
            </div>
            ${reasonHtml}
            ${alertsHtml}
        </div>`;
    },

    async loadRange(range, event) {
        document.querySelectorAll("#chart-range-btns .btn").forEach(b => b.classList.remove("active"));
        if (event?.target) event.target.classList.add("active");

        const now = Math.floor(Date.now() / 1000);
        let fromTs;
        let limit;
        switch (range) {
            case "24h": fromTs = now - 86400; limit = 500; break;
            case "7d": fromTs = now - 604800; limit = 2000; break;
            case "30d": fromTs = now - 2592000; limit = 5000; break;
            case "max": fromTs = 0; limit = 50000; break;
            default: fromTs = now - 86400; limit = 500;
        }

        try {
            const history = await App.api(
                `/devices/${encodeURIComponent(this.mac)}/history?limit=${limit}&from_ts=${fromTs}`
            );
            const device = await App.api(`/devices/${encodeURIComponent(this.mac)}`);
            this.renderChart(history, device.config?.target_soil_pct ?? 50);
        } catch (e) {
            App.showToast(`Fehler beim Laden: ${e.message}`, "danger");
        }
    },

    switchTab(tab) {
        const tabs = ['overview', 'diagnostics', 'messdaten'];
        document.querySelectorAll(".tab").forEach((t, i) => {
            t.classList.toggle("active", tabs[i] === tab);
        });
        tabs.forEach(name => {
            const el = document.getElementById("tab-" + name);
            if (el) el.classList.toggle("active", name === tab);
        });
        if (tab === 'messdaten' && !this.messdatenLoaded) {
            this.messdatenLoaded = true;
            this.loadMessdaten(0);
        }
    },

    onDataReceived(mac, measurement) {
        if (mac !== this.mac) return;
        if (!this._pendingMeasurements) this._pendingMeasurements = [];
        this._pendingMeasurements.push(measurement);
        if (this._flushPending) return;
        this._flushPending = true;
        requestAnimationFrame(() => this._flushMeasurements());
    },

    _flushMeasurements() {
        this._flushPending = false;
        const batch = this._pendingMeasurements || [];
        this._pendingMeasurements = [];
        if (batch.length === 0 || !this.mac) return;
        const mac = this.mac;
        const latest = batch[batch.length - 1];

        App.api(`/devices/${encodeURIComponent(mac)}`).then(device => {
            if (mac !== this.mac) return;
            const target = device.config?.target_soil_pct ?? 50;

            // Live-Stats + Gauge
            const statsEl = document.getElementById("live-stats");
            if (statsEl) {
                const irrigatedTs = device.last_irrigated_ts || 0;
                statsEl.innerHTML = this.liveStatsHtml(latest, device, irrigatedTs);
                const pct = latest.soil_pct ?? 0;
                const gaugeFill = document.getElementById("gauge-fill");
                const gaugeVal = document.getElementById("gauge-value");
                const gaugeStatus = document.getElementById("gauge-status");
                if (gaugeFill) {
                    gaugeFill.style.background = `conic-gradient(${this.gaugeColor(pct, target)} ${pct * 3.6}deg, var(--border) ${pct * 3.6}deg)`;
                }
                if (gaugeVal) gaugeVal.textContent = pct + '%';
                if (gaugeStatus) {
                    gaugeStatus.innerHTML = `
                        <span style="color:${this.gaugeColor(pct, target)}">${this.gaugeStatusText(pct, target)}</span>
                        <span class="gauge-target-label">Ziel: ${target}%</span>`;
                }
            }

            // Diagnostik-Karten
            const diagEl = document.getElementById("diag-stats");
            if (diagEl) diagEl.innerHTML = this.diagCardsHtml(latest);

            // Chart: alle neuen Messpunkte anhängen und einmal neu zeichnen
            if (this.lastHistory) {
                let appended = false;
                let lastTs = this.lastHistory.length > 0
                    ? this.lastHistory[this.lastHistory.length - 1].timestamp : 0;
                for (const m of batch) {
                    const newTs = m.timestamp;
                    if (!newTs || newTs !== lastTs) {
                        this.lastHistory.push(m);
                        lastTs = newTs;
                        appended = true;
                    }
                }
                if (appended) this.renderChart(this.lastHistory, target);
            }

            // Messdaten-Tab: nur refreshen wenn sichtbar und auf erster Seite
            const messdatenTab = document.getElementById("tab-messdaten");
            if (this.messdatenLoaded && messdatenTab?.classList.contains("active")
                    && this.messdatenOffset === 0) {
                this.loadMessdaten(0);
            }
        }).catch(() => {});
    },

    onBrainDecision(mac, data) {
        if (mac !== this.mac) return;
        App.api(`/devices/${encodeURIComponent(mac)}`).then(device => {
            const insightEl = document.getElementById("insight-cards");
            if (insightEl) {
                const m = App.state.devices[mac] || {};
                m.brain_reasoning = data.reasoning || data.brain_reasoning;
                m.brain_sleep_s = data.sleep_s || data.brain_sleep_s;
                m.brain_irrigate = data.irrigate ?? data.brain_irrigate;
                m.alerts = data.alerts || [];
                insightEl.innerHTML =
                    this.weatherCardHtml(device) + this.brainCardHtml(m, device);
            }
        }).catch(() => {});
    },

    async saveNotes() {
        const textarea = document.getElementById("device-notes");
        if (!textarea) return;
        try {
            await App.api(`/devices/${encodeURIComponent(this.mac)}/notes`, {
                method: "PUT",
                body: JSON.stringify({ notes: textarea.value }),
            });
            App.showToast("Notiz gespeichert", "success", 3000);
        } catch (e) {
            App.showToast(`Fehler: ${e.message}`, "danger");
        }
    },

    async deleteDevice() {
        const ok = await App.confirm(
            "Gerät löschen?",
            "Alle Messdaten für dieses Gerät werden unwiderruflich gelöscht."
        );
        if (!ok) return;

        try {
            await App.api(`/devices/${encodeURIComponent(this.mac)}`, { method: "DELETE" });
            App.showToast("Gerät gelöscht", "success");
            App.navigate("/");
        } catch (e) {
            App.showToast(`Fehler: ${e.message}`, "danger");
        }
    },

    // ─── Messdaten-Tab ───

    MESSDATEN_COLS: [
        { key: 'measurement_id', label: '#', tip: 'Fortlaufende Messnummer' },
        { key: 'timestamp', label: 'Zeitpunkt', tip: 'Zeitstempel der Messung', fmt: v => v ? App.formatTimestamp(v) : '-' },
        { key: 'online', label: 'Online', tip: 'Live gesendet vs. nachträglich gebuffert', fmt: v => v === true || v === 'True' ? 'Ja' : 'Nein' },
        { key: 'soil_pct', label: 'Feuchte %', tip: 'Bodenfeuchte (0%=trocken, 100%=nass)', fmt: v => v != null ? v + '%' : '-' },
        { key: 'soil_raw', label: 'ADC Roh', tip: 'Roher ADC-Wert kapazitiver Sensor, höher=trockener' },
        { key: 'temp', label: 'Temp', tip: 'HTU21D Sensor, °C', fmt: v => v != null ? Number(v).toFixed(1) + '°C' : '-' },
        { key: 'rh', label: 'RH %', tip: 'Relative Luftfeuchtigkeit (HTU21D)', fmt: v => v != null ? Number(v).toFixed(0) + '%' : '-' },
        { key: 'vbat', label: 'Batterie', tip: 'LiPo Spannung (3.0-4.2V)', fmt: v => v != null ? Number(v).toFixed(2) + 'V' : '-' },
        { key: 'irrigated', label: 'Bewässert', tip: 'Ob in diesem Zyklus bewässert wurde', fmt: v => v === true || v === 'True' || v === '1' ? 'Ja' : 'Nein' },
        { key: 'irrigation_ms', label: 'Dauer', tip: 'Pumpenlaufzeit', fmt: v => v ? (v / 1000).toFixed(1) + 's' : '0' },
        { key: 'target_soil_pct', label: 'Ziel %', tip: 'Konfigurierte Ziel-Feuchte', fmt: v => v != null ? v + '%' : '-' },
        { key: 'brain_sleep_s', label: 'Schlaf', tip: 'Vom Brain berechnete Schlafzeit', fmt: v => v != null ? App.formatDuration(v) : '-' },
        { key: 'brain_reasoning', label: 'Brain', tip: 'Brain Begründung', extended: false, wrap: true },
    ],

    MESSDATEN_COLS_EXTENDED: [
        { key: 'irrigation_start_delta', label: 'Bewässerungs-Delta', tip: 'Hysterese unter dem Ziel (online und offline)' },
        { key: 'offline_sleep_s', label: 'Offline-Schlaf', tip: 'Schlafzeit wenn ESP32 offline', fmt: v => v != null ? v + 's' : '-' },
        { key: 'calib_dry', label: 'Kal. Trocken', tip: 'ADC bei 0% Feuchte' },
        { key: 'calib_wet', label: 'Kal. Nass', tip: 'ADC bei 100% Feuchte' },
        { key: 'total_irrigation_ms', label: 'Ges. Bew.', tip: 'Kumulierte Pumpenlaufzeit (NVS)', fmt: v => v != null ? (v / 1000).toFixed(0) + 's' : '-' },
        { key: 'total_wakeups', label: 'Wakeups', tip: 'Aufwach-Zyklen seit Factory Reset' },
        { key: 'avg_awake_s', label: 'Ø Wachzeit', tip: 'Durchschn. Wachzeit pro Zyklus', fmt: v => v != null ? Number(v).toFixed(1) + 's' : '-' },
        { key: 'ble_success_pct', label: 'BLE %', tip: 'BLE-Erfolgsrate', fmt: v => v != null ? Number(v).toFixed(0) + '%' : '-' },
        { key: 'total_awake_ms', label: 'Wachzeit ges.', tip: 'Kumulierte Wachzeit (NVS)', fmt: v => v != null ? (v / 1000).toFixed(0) + 's' : '-' },
        { key: 'last_awake_time_ms', label: 'Letzte Wachz.', tip: 'Wachzeit des vorherigen Zyklus', fmt: v => v != null ? v + ' ms' : '-' },
        { key: 'last_sleep_duration_s', label: 'Geplanter Schlaf', tip: 'Geplante Schlafzeit dieses Zyklus (aus NVS, kann bei Reset abweichen)', fmt: v => v != null ? App.formatDuration(v) : '-' },
        { key: 'actual_sleep', label: 'Tats. Schlaf', tip: 'Tatsächliche Dauer zwischen den Messungen (aus Timestamps); weicht vom Plan-Wert ab wenn der ESP32 z.B. per Reset frühzeitig geweckt wurde', fmt: (_, row, prevRow) => {
            if (!prevRow || !row.timestamp || !prevRow.timestamp) return '-';
            const delta = row.timestamp - prevRow.timestamp;
            if (delta <= 0) return '-';
            return App.formatDuration(delta);
        } },
        { key: 'uptime_seconds', label: 'Uptime', tip: 'Seit letztem Powercycle (RTC)', fmt: v => v != null ? App.formatDuration(v) : '-' },
        { key: 'free_heap_bytes', label: 'Heap', tip: 'Verfügbarer Speicher', fmt: v => v != null ? (v / 1024).toFixed(0) + ' KB' : '-' },
        { key: 'reset_reason', label: 'Reset', tip: 'Grund letzter Neustart', fmt: v => v != null ? App.resetReasonText(v) : '-' },
        { key: 'pump_dry', label: 'Trockenlauf', tip: 'Gegossen, aber die Bodenfeuchte ist nicht gestiegen (Tank leer?)', fmt: v => v === true ? 'Ja' : 'Nein' },
        // Leer bei gepufferten Messungen, über die das Brain nicht entschieden hat
        { key: 'brain_irrigate', label: 'Brain Bew.', tip: 'Brain empfiehlt Bewässerung', fmt: v => v == null || v === '' ? '-' : v === true || v === 'True' ? 'Ja' : 'Nein' },
    ],

    async loadMessdaten(offset) {
        this.messdatenOffset = offset;
        const wrapper = document.getElementById('messdaten-table-wrapper');
        const info = document.getElementById('messdaten-info');
        const pag = document.getElementById('messdaten-pagination');

        try {
            const data = await App.api(
                `/devices/${encodeURIComponent(this.mac)}/measurements?limit=${this.messdatenPageSize}&offset=${offset}`
            );
            this.messdatenTotal = data.total;
            const from = data.total > 0 ? offset + 1 : 0;
            const to = Math.min(offset + data.rows.length, data.total);
            info.textContent = `Zeige ${from}-${to} von ${data.total} Messungen`;

            wrapper.innerHTML = this.messdatenTableHtml(data.rows);
            pag.innerHTML = this.messdatenPaginationHtml(offset, data.total);
        } catch (e) {
            wrapper.innerHTML = `<p style="color:var(--danger);padding:1rem">Fehler: ${e.message}</p>`;
            info.textContent = '';
            pag.innerHTML = '';
        }
    },

    messdatenTableHtml(rows) {
        if (!rows.length) return '<p style="padding:1rem;opacity:0.6">Keine Messdaten vorhanden.</p>';

        const cols = this.MESSDATEN_COLS;
        const extCols = this.MESSDATEN_COLS_EXTENDED;
        const showExt = this.messdatenShowExtended;
        const extClass = showExt ? ' show-extended' : '';

        let html = `<table class="messdaten-table${extClass}">`;
        html += '<thead><tr>';
        for (const c of cols) {
            html += `<th title="${this.esc(c.tip)}">${this.esc(c.label)}</th>`;
        }
        for (const c of extCols) {
            html += `<th class="col-extended" title="${this.esc(c.tip)}">${this.esc(c.label)}</th>`;
        }
        html += '</tr></thead><tbody>';

        for (let i = 0; i < rows.length; i++) {
            const row = rows[i];
            const prevRow = rows[i + 1];
            html += '<tr>';
            for (const c of cols) {
                const val = row[c.key];
                const display = c.fmt ? c.fmt(val, row, prevRow) : (val ?? '-');
                const cls = c.wrap ? ' class="col-wrap"' : '';
                html += `<td${cls}>${c.wrap ? this.esc(String(display)) : display}</td>`;
            }
            for (const c of extCols) {
                const val = row[c.key];
                const display = c.fmt ? c.fmt(val, row, prevRow) : (val ?? '-');
                html += `<td class="col-extended">${display}</td>`;
            }
            html += '</tr>';
        }

        html += '</tbody></table>';
        return html;
    },

    messdatenPaginationHtml(offset, total) {
        if (total <= this.messdatenPageSize) return '';
        const page = Math.floor(offset / this.messdatenPageSize) + 1;
        const totalPages = Math.ceil(total / this.messdatenPageSize);
        const prevDisabled = offset <= 0 ? ' disabled' : '';
        const nextDisabled = offset + this.messdatenPageSize >= total ? ' disabled' : '';
        const prevOffset = Math.max(0, offset - this.messdatenPageSize);
        const nextOffset = offset + this.messdatenPageSize;

        return `
            <button class="btn btn-outline btn-sm"${prevDisabled} onclick="Details.loadMessdaten(${prevOffset})">
                <svg width="14" height="14"><use href="#icon-arrow-left"/></svg> Zurück
            </button>
            <span class="messdaten-page-info">Seite ${page} / ${totalPages}</span>
            <button class="btn btn-outline btn-sm"${nextDisabled} onclick="Details.loadMessdaten(${nextOffset})">
                Weiter <svg width="14" height="14" style="transform:rotate(180deg)"><use href="#icon-arrow-left"/></svg>
            </button>
        `;
    },

    toggleExtendedCols() {
        this.messdatenShowExtended = !this.messdatenShowExtended;
        const table = document.querySelector('.messdaten-table');
        const btn = document.getElementById('messdaten-toggle-cols');
        if (table) table.classList.toggle('show-extended', this.messdatenShowExtended);
        if (btn) btn.classList.toggle('active', this.messdatenShowExtended);
    },

    esc(str) {
        return App.esc(str);
    },
};

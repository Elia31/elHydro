// dashboard.js - Geräte-Übersicht mit Begrüßung und Stats

const Dashboard = {
    container: null,
    devices: null,

    async render(el) {
        this.container = el;
        this.devices = null;

        // Skeleton-Ladeanzeige
        el.innerHTML = `
            <div class="page-enter">
                <div class="dashboard-hero-banner" style="min-height:140px">
                    <div class="hero-banner-content">
                        <div class="skeleton-line w-60" style="height:24px"></div>
                    </div>
                </div>
                <div class="device-grid">
                    ${Array(2).fill('<div class="skeleton-card"><div class="skeleton-line w-60"></div><div class="skeleton-line w-40"></div><div class="skeleton-circle"></div><div class="skeleton-line w-80"></div></div>').join('')}
                </div>
            </div>
        `;

        try {
            const devices = await App.api("/devices");

            // Letzte Messung pro Gerät holen, damit Karten beim ersten Laden Daten zeigen
            await Promise.all(devices.map(async (d) => {
                if (!App.state.devices[d.mac]) {
                    try {
                        const hist = await App.api(`/devices/${encodeURIComponent(d.mac)}/history?limit=1`);
                        if (hist.length > 0) App.state.devices[d.mac] = hist[0];
                    } catch (_) { /* ignore */ }
                }
            }));

            this.devices = devices;
            el.innerHTML = `<div class="page-enter">${this.buildInnerHtml(devices, true)}</div>`;
        } catch (e) {
            el.innerHTML = `<p style="color:var(--danger)">Fehler: ${e.message}</p>`;
        }
    },

    buildInnerHtml(devices, animate) {
        return `
            ${this.greetingHtml(devices)}
            ${devices.length > 0 ? '<h2 class="section-title">Meine Geräte</h2>' : ''}
            <div class="device-grid" id="device-grid">
                ${devices.length === 0 ? this.emptyStateHtml() : devices.map((d, i) => this.cardHtml(d, i, animate)).join("")}
            </div>
        `;
    },

    updateCards() {
        if (!this.container || !this.devices) return;
        const wrapper = this.container.querySelector(".page-enter");
        if (!wrapper) return;

        for (const d of this.devices) {
            const m = App.state.devices[d.mac];
            if (m && typeof m.timestamp === "number" && m.timestamp > (d.last_seen || 0)) {
                d.last_seen = m.timestamp;
            }
        }

        wrapper.innerHTML = this.buildInnerHtml(this.devices, false);
    },

    greetingHtml(devices) {
        const hour = new Date().getHours();
        let greeting, iconId;
        if (hour < 6)       { greeting = "Gute Nacht"; iconId = "icon-moon"; }
        else if (hour < 12) { greeting = "Guten Morgen"; iconId = "icon-sunrise"; }
        else if (hour < 18) { greeting = "Guten Tag"; iconId = "icon-sun"; }
        else                { greeting = "Guten Abend"; iconId = "icon-moon"; }

        const sun = this.sunTimes();
        const sunHtml = sun ? `
            <div class="hero-sun">
                <svg width="18" height="18"><use href="#icon-sunrise"/></svg>
                <span>${sun.rise}</span>
                <span class="hero-sun-sep">-</span>
                <svg width="18" height="18"><use href="#icon-sunset"/></svg>
                <span>${sun.set}</span>
            </div>` : '';

        const statsHtml = devices.length > 0 ? this.statsRowHtml(devices) : '';

        // Untertitel je nach Gerätezustand
        let subtitle;
        if (devices.length === 0) {
            subtitle = "Noch keine Geräte registriert";
        } else {
            const warnings = this.countWarnings(devices);
            if (warnings.hasDanger) {
                subtitle = "Einige Geräte brauchen Aufmerksamkeit";
            } else if (warnings.count > 0) {
                subtitle = "Dein Garten könnte etwas Pflege vertragen";
            } else {
                subtitle = "Deinen Pflanzen geht es gut";
            }
        }

        return `
            <div class="dashboard-hero-banner">
                <div class="hero-banner-content hero-banner-split">
                    <div class="hero-banner-left">
                        <div class="hero-banner-heading">
                            <svg class="hero-banner-icon"><use href="#${iconId}"/></svg>
                            <h1 class="hero-banner-title">${greeting}</h1>
                        </div>
                        ${sunHtml}
                        <p class="hero-banner-subtitle">${subtitle}</p>
                    </div>
                    <div class="hero-banner-right">
                        ${statsHtml}
                    </div>
                </div>
            </div>
        `;
    },

    sunTimes() {
        // Sonnenauf/-untergang für Mitteldeutschland (~51°N, 10°E)
        const lat = 51.1, lng = 10.4;
        const D2R = Math.PI / 180, R2D = 180 / Math.PI;
        const now = new Date();
        const janFirst = new Date(now.getFullYear(), 0, 1);
        const dayOfYear = Math.floor((now - janFirst) / 86400000) + 1;
        const lngHour = lng / 15;

        function calc(rise) {
            const t = dayOfYear + ((rise ? 6 : 18) - lngHour) / 24;
            const M = (0.9856 * t) - 3.289;
            let L = M + 1.916 * Math.sin(M * D2R) + 0.020 * Math.sin(2 * M * D2R) + 282.634;
            L = ((L % 360) + 360) % 360;
            let RA = R2D * Math.atan(0.91764 * Math.tan(L * D2R));
            RA = ((RA % 360) + 360) % 360;
            RA = (RA + Math.floor(L / 90) * 90 - Math.floor(RA / 90) * 90) / 15;
            const sinDec = 0.39782 * Math.sin(L * D2R);
            const cosDec = Math.cos(Math.asin(sinDec));
            const cosH = (Math.cos(90.833 * D2R) - sinDec * Math.sin(lat * D2R)) / (cosDec * Math.cos(lat * D2R));
            if (cosH > 1 || cosH < -1) return null;
            let H = R2D * Math.acos(cosH);
            H = rise ? (360 - H) / 15 : H / 15;
            const T = H + RA - 0.06571 * t - 6.622;
            let utc = ((T - lngHour) % 24 + 24) % 24;
            // UTC zu lokaler Zeit über Browser-Timezone
            utc -= now.getTimezoneOffset() / 60;
            utc = ((utc % 24) + 24) % 24;
            const h = Math.floor(utc);
            const m = Math.round((utc - h) * 60);
            return `${h}:${m.toString().padStart(2, '0')}`;
        }

        const rise = calc(true);
        const set = calc(false);
        if (!rise || !set) return null;
        return { rise, set };
    },

    statsRowHtml(devices) {
        const total = devices.length;
        const now = Math.floor(Date.now() / 1000);
        const active = devices.filter(d => d.last_seen && (now - d.last_seen) < 3600).length;
        const warnings = this.countWarnings(devices);
        const driest = this.driestPlant(devices);

        const lowestBat = this.lowestBatteryInfo(devices);

        return `
            <div class="stats-summary-row">
                <div class="stat-summary-card">
                    <div class="stat-summary-icon green"><svg><use href="#icon-leaf"/></svg></div>
                    <div class="stat-summary-value">${total}</div>
                    <div class="stat-summary-label">${active} kürzlich aktiv</div>
                </div>
                <div class="stat-summary-card">
                    <div class="stat-summary-icon ${warnings.count > 0 ? (warnings.hasDanger ? 'red' : 'amber') : 'green'}">
                        <svg><use href="#${warnings.count > 0 ? 'icon-alert-triangle' : 'icon-check'}"/></svg>
                    </div>
                    <div class="stat-summary-value">${warnings.count > 0 ? warnings.count : '✓'}</div>
                    <div class="stat-summary-label">${warnings.count > 0 ? 'Probleme' : 'Alles OK'}</div>
                </div>
                <div class="stat-summary-card">
                    <div class="stat-summary-icon ${driest.cls}"><svg><use href="#icon-droplet"/></svg></div>
                    <div class="stat-summary-value">${driest.value}</div>
                    <div class="stat-summary-label">${driest.label}</div>
                </div>
                <div class="stat-summary-card">
                    <div class="stat-summary-icon ${lowestBat.cls}"><svg><use href="#icon-battery"/></svg></div>
                    <div class="stat-summary-value">${lowestBat.value}</div>
                    <div class="stat-summary-label">Schwächster Akku</div>
                </div>
            </div>
        `;
    },

    lowestBatteryInfo(devices) {
        let lowest = null;
        for (const d of devices) {
            const v = App.state.devices[d.mac]?.vbat;
            if (typeof v === 'number' && v > 0) {
                if (lowest === null || v < lowest) lowest = v;
            }
        }
        if (lowest === null) return { value: '-', cls: 'green' };
        const pct = App.batteryPercent(lowest);
        const cls = pct < 10 ? 'red' : pct < 20 ? 'amber' : 'green';
        return { value: pct + '%', cls };
    },

    driestPlant(devices) {
        let driest = null;
        let driestName = null;
        for (const d of devices) {
            const m = App.state.devices[d.mac];
            if (!m || typeof m.soil_pct !== 'number') continue;
            if (driest === null || m.soil_pct < driest) {
                driest = m.soil_pct;
                driestName = d.name || d.mac;
            }
        }
        if (driest === null) return { value: '-', label: 'Trockenste', cls: 'blue' };
        const cls = driest < 30 ? 'amber' : 'blue';
        return { value: driest + '%', label: 'Trockenste', cls };
    },

    emptyStateHtml() {
        return `
            <div class="empty-state" style="grid-column: 1/-1">
                <div class="empty-state-icon">
                    <svg width="64" height="64" style="color:var(--primary);opacity:0.4"><use href="#icon-plant"/></svg>
                </div>
                <p>Noch keine Geräte registriert.</p>
                <p class="text-muted" style="font-size:0.85rem;margin-bottom:1rem">Füge dein erstes elHydro-Gerät hinzu, um loszulegen.</p>
                <a href="/add" onclick="return App.link(event)" class="btn btn-primary">
                    <svg><use href="#icon-plus"/></svg>
                    Gerät hinzufügen
                </a>
            </div>
        `;
    },

    cardHtml(dev, index, animate = true) {
        const mac = dev.mac;
        const name = dev.name || mac;
        const lastMeasurement = App.state.devices[mac] || {};
        const soil = lastMeasurement.soil_pct ?? "-";
        const temp = lastMeasurement.temp;
        const rh = lastMeasurement.rh;
        const target = dev.config?.target_soil_pct ?? 50;
        const vbat = lastMeasurement.vbat ?? 0;
        const lastSeen = dev.last_seen;
        const soilNum = typeof soil === "number" ? soil : 0;
        const soilCls = typeof soil === "number" ? App.soilClass(soil, target) : "good";
        const typeIconId = dev.type === "outdoor" ? "icon-sun" : "icon-home";

        const statusInfo = this.statusDot(lastSeen);
        const delay = Math.min(index * 0.08, 0.4);
        const animStyle = animate ? `animation-delay:${delay}s` : "animation:none";

        // Gauge-Farbe je nach Health-Status
        let gaugeColor;
        switch (soilCls) {
            case "danger": gaugeColor = "var(--danger)"; break;
            case "warning": gaugeColor = "var(--warning)"; break;
            case "wet": gaugeColor = "var(--info)"; break;
            default: gaugeColor = "#16a34a"; break;
        }

        // Bodenfeuchte-Status-Badge
        const delta = dev.config?.irrigation_start_delta ?? 10;
        const soilStatus = this.soilStatusText(soil, target, delta);

        // Warning line (Priorität: Batterie → Offline >3d → kritisch trocken → Frost/Hitze → Überwässert → Sensor → Offline >1d)
        const now = Math.floor(Date.now() / 1000);
        const ageSec = lastSeen ? (now - lastSeen) : Infinity;
        const isOutdoor = dev.type === "outdoor";

        let warningHtml = '';
        if (vbat > 0 && vbat < 3.3) {
            const bPct = App.batteryPercent(vbat);
            warningHtml = `<div class="card-warning danger-text"><svg width="12" height="12"><use href="#icon-battery"/></svg> Batterie fast leer (${bPct}%)</div>`;
        } else if (ageSec > 3 * 86400) {
            const days = Math.floor(ageSec / 86400);
            warningHtml = `<div class="card-warning danger-text"><svg width="12" height="12"><use href="#icon-alert-triangle"/></svg> Seit ${days} Tagen offline<br>Bitte Gerät überprüfen</div>`;
        } else if (App.criticalSoil(lastMeasurement, target, delta)) {
            const text = lastMeasurement.irrigated
                ? "Bewässert, aber Boden bleibt trocken - Tank prüfen"
                : "Boden zu trocken - Bewässerung prüfen";
            warningHtml = `<div class="card-warning danger-text"><svg width="12" height="12"><use href="#icon-alert-triangle"/></svg> ${text}</div>`;
        } else if (App.frostRisk(lastMeasurement, isOutdoor)) {
            warningHtml = `<div class="card-warning warning-text"><svg width="12" height="12"><use href="#icon-alert-triangle"/></svg> Frost (${temp.toFixed(1)}°C) - Bewässerung gesperrt</div>`;
        } else if (App.heatRisk(lastMeasurement, isOutdoor)) {
            warningHtml = `<div class="card-warning warning-text"><svg width="12" height="12"><use href="#icon-alert-triangle"/></svg> Hitze (${temp.toFixed(1)}°C) - Pflanze gefährdet</div>`;
        } else if (App.overwatered(lastMeasurement, target)) {
            warningHtml = `<div class="card-warning warning-text"><svg width="12" height="12"><use href="#icon-humidity"/></svg> Sehr feucht - Staunässe möglich</div>`;
        } else if (App.sensorFail(lastMeasurement)) {
            warningHtml = `<div class="card-warning warning-text"><svg width="12" height="12"><use href="#icon-alert-triangle"/></svg> Bodensensor liefert keinen Wert</div>`;
        } else if (ageSec > 86400) {
            const days = Math.floor(ageSec / 86400);
            warningHtml = `<div class="card-warning warning-text"><svg width="12" height="12"><use href="#icon-alert-triangle"/></svg> Seit ${days} ${days === 1 ? 'Tag' : 'Tagen'} offline</div>`;
        }

        return `
            <div class="device-card health-${soilCls}" onclick="App.navigate('/device/${encodeURIComponent(mac)}')" style="${animStyle}">
                <div class="card-header">
                    <div class="card-header-left">
                        <div class="card-type-badge">
                            <svg><use href="#${typeIconId}"/></svg>
                        </div>
                        <div>
                            <div class="card-name">${this.esc(name)}</div>
                            ${warningHtml}
                        </div>
                    </div>
                    <div class="card-gauge-wrap">
                        <div class="card-gauge" style="--gauge-pct:${soilNum};--gauge-color:${gaugeColor}">
                            <div class="card-gauge-inner">
                                <span class="card-gauge-value">${soil}${typeof soil === 'number' ? '%' : ''}</span>
                            </div>
                        </div>
                        <span class="card-gauge-target-label">Ziel ${target}%</span>
                    </div>
                </div>
                <div class="soil-status-badge ${soilStatus.cls}">${soilStatus.text}</div>
                <div class="card-stats-row">
                    <div class="card-stat temp">
                        <svg><use href="#icon-thermometer"/></svg>
                        <span>${typeof temp === 'number' ? temp.toFixed(1) + '°C' : '-'}</span>
                    </div>
                    <div class="card-stat humidity">
                        <svg><use href="#icon-humidity"/></svg>
                        <span>${typeof rh === 'number' ? Math.round(rh) + '%' : '-'}</span>
                    </div>
                </div>
                <div class="card-footer">
                    <span title="${App.formatTimestamp(lastSeen)}">${App.timeAgo(lastSeen)}</span>
                    <span>${App.batteryHtml(vbat)}</span>
                    <div class="card-actions" onclick="event.stopPropagation()">
                        <button class="btn btn-outline btn-sm" onclick="App.navigate('/settings/${encodeURIComponent(mac)}')" title="Einstellungen">
                            <svg width="14" height="14"><use href="#icon-settings"/></svg>
                        </button>
                    </div>
                </div>
            </div>
        `;
    },

    countWarnings(devices) {
        const now = Math.floor(Date.now() / 1000);
        let count = 0;
        let hasDanger = false;
        for (const d of devices) {
            const m = App.state.devices[d.mac];
            const ageSec = d.last_seen ? (now - d.last_seen) : Infinity;
            const target = d.config?.target_soil_pct ?? 50;
            const delta = d.config?.irrigation_start_delta;
            const isOutdoor = d.type === "outdoor";

            // Gleiche Prioritätskette wie cardHtml
            if (!d.last_seen) {
                count++;
            } else if (m && m.vbat > 0 && m.vbat < 3.3) {
                count++; hasDanger = true;
            } else if (ageSec > 3 * 86400) {
                count++; hasDanger = true;
            } else if (App.criticalSoil(m, target, delta)) {
                count++; hasDanger = true;
            } else if (App.frostRisk(m, isOutdoor) || App.heatRisk(m, isOutdoor)) {
                count++;
            } else if (App.overwatered(m, target)) {
                count++;
            } else if (App.sensorFail(m)) {
                count++;
            } else if (ageSec > 86400) {
                count++;
            }
        }
        return { count, hasDanger };
    },

    soilStatusText(soil, target, delta) {
        if (typeof soil !== "number") return { text: "-", cls: "good" };
        // Gleiche Schwellen-Formel wie Firmware + Brain
        const targetMin = Math.max(Math.floor(target * 0.2), 5);
        const threshold = Math.max(target - delta, targetMin);

        if (soil >= target + 20) return { text: "Sehr feucht", cls: "wet" };
        if (soil >= target - 5)  return { text: "Optimal", cls: "good" };
        if (soil >= threshold)   return { text: "Etwas trocken", cls: "warning" };
        return { text: "Zu trocken!", cls: "danger" };
    },

    onDataReceived(mac, measurement) {
        if (App.currentView !== "dashboard") return;
        if (this._renderPending) return;
        this._renderPending = true;
        requestAnimationFrame(() => {
            this._renderPending = false;
            if (App.currentView !== "dashboard" || !this.container) return;
            this.updateCards();
        });
    },

    statusDot(lastSeen) {
        if (!lastSeen || lastSeen === 0) {
            return { cls: "status-never", label: "Verbinde\u2026" };
        }
        const ageSec = Math.floor(Date.now() / 1000) - lastSeen;
        if (ageSec < 300) {
            return { cls: "status-recent", label: "Gerade aktiv" };
        } else if (ageSec < 3600) {
            return { cls: "status-recent", label: `vor ${Math.floor(ageSec / 60)} Min.` };
        } else if (ageSec < 14400) {
            return { cls: "status-idle", label: `vor ${Math.floor(ageSec / 3600)} Std.` };
        } else {
            return { cls: "status-stale", label: App.timeAgo(lastSeen) };
        }
    },

    esc(str) {
        const d = document.createElement("div");
        d.textContent = str;
        return d.innerHTML;
    },
};

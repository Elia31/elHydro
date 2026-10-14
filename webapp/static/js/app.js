// app.js - Router, WebSocket Client, Globaler State

const App = {
    state: {
        devices: {},
        scanResults: [],
        lastLog: "",
    },
    ws: null,
    currentView: null,
    reconnectDelay: 1000,

    // --- Router ---
    init() {
        window.addEventListener("popstate", () => App.route());
        App.connectWebSocket();
        App.loadTheme();
        App.createMobileNav();
        App.route();
    },

    navigate(path) {
        history.pushState(null, "", path);
        App.route();
    },

    link(event) {
        event.preventDefault();
        const href = event.currentTarget.getAttribute("href");
        App.navigate(href);
        return false;
    },

    route() {
        const path = location.pathname;
        const app = document.getElementById("app");

        // Nav-Links aktiv markieren
        document.querySelectorAll(".nav-link").forEach(l => {
            const href = l.getAttribute("href");
            l.classList.toggle("active", href === path || (path === "/" && l.dataset.page === "dashboard"));
        });

        if (path === "/" || path === "") {
            App.currentView = "dashboard";
            Dashboard.render(app);
        } else if (path === "/add") {
            App.currentView = "add";
            AddDevice.render(app);
        } else if (path.startsWith("/device/")) {
            App.currentView = "details";
            const mac = decodeURIComponent(path.replace("/device/", ""));
            Details.render(app, mac);
        } else if (path === "/presets") {
            App.currentView = "presets";
            PresetEditor.render(app);
        } else if (path === "/logs") {
            App.currentView = "logs";
            Logs.render(app);
        } else if (path.startsWith("/settings/")) {
            App.currentView = "settings";
            const mac = decodeURIComponent(path.replace("/settings/", ""));
            Settings.render(app, mac);
        } else {
            App.currentView = "dashboard";
            Dashboard.render(app);
        }
    },

    // --- WebSocket ---
    connectWebSocket() {
        const proto = location.protocol === "https:" ? "wss:" : "ws:";
        App.ws = new WebSocket(`${proto}//${location.host}/ws`);

        App.ws.onopen = () => {
            App.reconnectDelay = 1000;
            App.setWsStatus(true);
            App.setStatus("Server verbunden");
        };

        App.ws.onclose = () => {
            App.setWsStatus(false);
            App.setStatus("Verbindung getrennt - Reconnect...");
            setTimeout(() => {
                App.reconnectDelay = Math.min(App.reconnectDelay * 1.5, 10000);
                App.connectWebSocket();
            }, App.reconnectDelay);
        };

        App.ws.onerror = () => {
            App.ws.close();
        };

        App.ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                App.handleEvent(msg.event, msg.data);
            } catch (e) {
                console.error("WS parse error:", e);
            }
        };
    },

    handleEvent(event, data) {
        switch (event) {
            case "device_found":
                App.state.scanResults = App.state.scanResults.filter(d => d.mac !== data.mac);
                App.state.scanResults.push(data);
                if (App.currentView === "add") AddDevice.onDeviceFound(data);
                break;

            case "device_connected":
                App.setBleStatus(true);
                break;

            case "device_disconnected":
                App.setBleStatus(false);
                break;

            case "data_received":
                App.state.devices[data.mac] = data.measurement;
                if (App.currentView === "dashboard") Dashboard.onDataReceived(data.mac, data.measurement);
                if (App.currentView === "details") Details.onDataReceived(data.mac, data.measurement);
                App.checkAlerts(data.mac, data.measurement);
                break;

            case "log":
                App.state.lastLog = data.message;
                App.setStatus(data.message);
                if (App.currentView === "logs") Logs.onLogReceived(data);
                break;

            case "brain_decision":
                if (App.currentView === "details") Details.onBrainDecision(data.mac, data);
                break;

            case "alert":
                App.showToast(data.message, data.type || "info");
                break;
        }
    },

    // --- Zustands-Checks für Warnungen ---
    // Gleiche Werte wie brain.py und config.h (der Test test_firmware_sync.py prüft das)
    IRR_THRESHOLD_TARGET_RATIO: 0.2,
    IRR_THRESHOLD_MIN_ABS: 5,

    // Gieß-Schwelle wie Firmware und Brain: max(target - delta, 20 % vom Ziel, 5 %)
    soilThreshold(target, delta) {
        const targetMin = Math.max(Math.floor(target * App.IRR_THRESHOLD_TARGET_RATIO), App.IRR_THRESHOLD_MIN_ABS);
        return Math.max(target - delta, targetMin);
    },

    criticalSoil(m, target, delta) {
        if (!m || typeof m.soil_pct !== "number") return false;
        const t = target ?? m.target_soil_pct ?? 50;
        const d = delta ?? m.irrigation_start_delta ?? 10;
        return m.soil_pct < App.soilThreshold(t, d);
    },

    overwatered(m, target) {
        if (!m || typeof m.soil_pct !== "number") return false;
        const t = target ?? m.target_soil_pct ?? 50;
        return m.soil_pct >= t + 20;
    },

    frostRisk(m, isOutdoor) {
        return !!isOutdoor && typeof m?.temp === "number" && m.temp <= 0;
    },

    heatRisk(m, isOutdoor) {
        return !!isOutdoor && typeof m?.temp === "number" && m.temp > 40;
    },

    sensorFail(m) {
        if (!m) return false;
        const online = m.online === true || m.online === 1 || m.online === "True" || m.online === "true" || m.online === "1";
        return online && (m.soil_pct === null || m.soil_pct === undefined);
    },

    // --- Alerts ---
    checkAlerts(mac, m) {
        // Toast nur bei frischer Bewässerung, die nichts gebracht hat. Die Messung
        // nach dem Gießen kommt beim nächsten Kontakt als gepufferte Messung.
        // Hat die Firmware einen Trockenlauf erkannt (pump_dry), meldet das schon der Server.
        if (m.irrigated && !m.pump_dry && typeof m.soil_pct === "number") {
            const threshold = App.soilThreshold(m.target_soil_pct || 50, m.irrigation_start_delta || 10);
            if (m.soil_pct < threshold - 5) {
                App.showToast(`${mac}: Bewässert, aber Boden bleibt trocken (${m.soil_pct}%) - Wassertank prüfen`, "warning");
            }
        }

        // Batterie nur bei der aktuellen Messung prüfen, sonst kommt beim
        // Nachsenden eines Puffers für jede gepufferte Messung ein eigener Hinweis
        if (!(m.online === true || m.online === 1)) return;

        // Batterie-Warnungen
        if (m.vbat > 0 && m.vbat < 3.2) {
            App.showToast(`${mac}: Batterie kritisch (${App.batteryPercent(m.vbat)}%) - bitte laden`, "danger");
        } else if (m.vbat > 0 && m.vbat < 3.4) {
            App.showToast(`${mac}: Batterie wird schwach (${App.batteryPercent(m.vbat)}%)`, "warning");
        }
    },

    // --- Toast ---
    showToast(message, type = "info", duration = 10000) {
        const container = document.getElementById("toast-container");
        const toast = document.createElement("div");
        toast.className = `toast ${type}`;

        const iconMap = {
            success: "icon-check",
            danger: "icon-x-circle",
            warning: "icon-alert-triangle",
            info: "icon-info",
        };
        const iconId = iconMap[type] || "icon-info";

        toast.style.setProperty('--toast-duration', (duration / 1000) + 's');
        toast.innerHTML = `<svg><use href="#${iconId}"/></svg><span>${this.esc(message)}</span><div class="toast-progress"></div>`;
        toast.onclick = () => toast.remove();
        container.appendChild(toast);
        setTimeout(() => {
            if (toast.parentNode) toast.remove();
        }, duration);
    },

    // Für Text und Attributwerte: innerHTML allein maskiert keine Anführungszeichen,
    // ein Name wie 6" Topf würde sonst value="..." vorzeitig beenden
    esc(str) {
        const d = document.createElement("div");
        d.textContent = str ?? "";
        return d.innerHTML.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    },

    // --- Theme ---
    toggleTheme() {
        const html = document.documentElement;
        const current = html.getAttribute("data-theme");
        const next = current === "dark" ? "light" : "dark";
        html.setAttribute("data-theme", next);
        localStorage.setItem("elhydro-theme", next);
        App.updateThemeIcon(next);
    },

    loadTheme() {
        let saved = localStorage.getItem("elhydro-theme");
        if (!saved) {
            // Systemeinstellung als Default
            saved = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
        }
        document.documentElement.setAttribute("data-theme", saved);
        App.updateThemeIcon(saved);
    },

    updateThemeIcon(theme) {
        const sunEl = document.getElementById("theme-icon-sun");
        const moonEl = document.getElementById("theme-icon-moon");
        if (sunEl && moonEl) {
            sunEl.style.display = theme === "dark" ? "none" : "inline";
            moonEl.style.display = theme === "dark" ? "inline" : "none";
        }
    },

    // --- UI Helpers ---
    setStatus(text) {
        document.getElementById("status-text").textContent = text;
    },

    setWsStatus(connected) {
        const el = document.getElementById("ws-status");
        el.className = "ws-indicator " + (connected ? "connected" : "disconnected");
    },

    setBleStatus(connected) {
        const el = document.getElementById("ble-status");
        el.className = "ble-status " + (connected ? "connected" : "");
        const footerEl = document.getElementById("ble-status-footer");
        if (footerEl) footerEl.className = "ws-indicator " + (connected ? "connected" : "disconnected");
    },

    createMobileNav() {
        if (document.querySelector(".mobile-nav")) return;
        const nav = document.createElement("div");
        nav.className = "mobile-nav mobile-only";
        nav.innerHTML = `
            <a href="/" class="nav-link" data-page="dashboard" onclick="return App.link(event)">
                <svg class="nav-link-icon"><use href="#icon-home"/></svg>
                Dashboard
            </a>
            <a href="/add" class="nav-link" data-page="add" onclick="return App.link(event)">
                <svg class="nav-link-icon"><use href="#icon-plus"/></svg>
                Hinzufügen
            </a>
            <a href="/presets" class="nav-link" data-page="presets" onclick="return App.link(event)">
                <svg class="nav-link-icon"><use href="#icon-sliders"/></svg>
                Presets
            </a>
            <a href="/logs" class="nav-link" data-page="logs" onclick="return App.link(event)">
                <svg class="nav-link-icon"><use href="#icon-info"/></svg>
                Logs
            </a>
        `;
        document.body.appendChild(nav);
    },

    // --- API Helpers ---
    async api(path, options = {}) {
        const resp = await fetch(`/api${path}`, {
            headers: { "Content-Type": "application/json" },
            ...options,
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            // Validierungsfehler (422) liefern eine Liste statt eines Textes
            const detail = Array.isArray(err.detail) ? err.detail.map(d => d.msg).join(", ") : err.detail;
            throw new Error(detail || "API Fehler");
        }
        if (options.raw) return resp;
        return resp.json();
    },

    // --- Confirm Dialog ---
    confirm(title, text) {
        return new Promise((resolve) => {
            const overlay = document.createElement("div");
            overlay.className = "dialog-overlay";
            overlay.innerHTML = `
                <div class="dialog">
                    <div class="dialog-title">${title}</div>
                    <div class="dialog-text">${text}</div>
                    <div class="dialog-actions">
                        <button class="btn btn-outline btn-sm" id="dlg-cancel">Abbrechen</button>
                        <button class="btn btn-danger btn-sm" id="dlg-confirm">Bestätigen</button>
                    </div>
                </div>
            `;
            document.body.appendChild(overlay);
            overlay.querySelector("#dlg-cancel").onclick = () => { overlay.remove(); resolve(false); };
            overlay.querySelector("#dlg-confirm").onclick = () => { overlay.remove(); resolve(true); };
            overlay.onclick = (e) => { if (e.target === overlay) { overlay.remove(); resolve(false); } };
        });
    },

    // --- Utility ---
    timeAgo(timestamp) {
        if (!timestamp) return "Nie";
        const diff = Math.floor(Date.now() / 1000) - timestamp;
        if (diff < 60) return "Gerade eben";
        if (diff < 3600) return `vor ${Math.floor(diff / 60)} Min.`;
        if (diff < 86400) return `vor ${Math.floor(diff / 3600)} Std.`;
        return `vor ${Math.floor(diff / 86400)} Tagen`;
    },

    batteryPercent(v) {
        // LiPo-Entladekurve (typisch, 0.2C)
        const t = [
            [4.20,100],[4.10,92],[4.00,83],[3.90,72],[3.80,59],
            [3.70,45],[3.60,30],[3.50,17],[3.40,8],[3.30,3],[3.00,0],
        ];
        if (!v || v <= 0) return 0;
        if (v >= 4.20) return 100;
        if (v <= 3.00) return 0;
        for (let i = 0; i < t.length - 1; i++) {
            const [v1, p1] = t[i], [v2, p2] = t[i + 1];
            if (v >= v2) return Math.round(p1 + (p2 - p1) * (v1 - v) / (v1 - v2));
        }
        return 0;
    },

    batteryHtml(vbat) {
        if (!vbat || vbat <= 0) return "";
        const rounded = Math.round(vbat * 100) / 100;
        const pct = App.batteryPercent(rounded);
        let cls;
        if (pct < 15) { cls = "critical"; }
        else if (pct < 30) { cls = "low"; }
        else { cls = "good"; }
        return `<span class="battery-icon ${cls}" title="~${pct}% (geschätzt)"><svg><use href="#icon-battery"/></svg> ${rounded.toFixed(2)} V (~${pct}%)</span>`;
    },

    soilClass(soil, target) {
        const diff = soil - target;
        if (diff < -10) return "danger";
        if (diff < -5) return "warning";
        if (diff > 20) return "wet";
        return "good";
    },

    resetReasonText(code) {
        const reasons = {
            0: "Unbekannt",
            1: "Power-On",
            2: "Pin-Reset",
            3: "Software-Reset",
            4: "Panic/Exception",
            5: "Interrupt-WDT",
            6: "Task-WDT",
            7: "WDT (Andere)",
            8: "Deep Sleep",
            9: "Brownout",
            10: "SDIO-Reset",
            11: "USB-Reset",
            12: "JTAG-Reset",
            13: "eFuse-Reset",
            14: "Power-Glitch",
            15: "CPU-Lockup",
        };
        return reasons[code] ?? `Code ${code}`;
    },

    timeUntil(timestamp) {
        if (!timestamp) return "";
        const diff = timestamp - Math.floor(Date.now() / 1000);
        if (diff <= 0) return "überfällig";
        if (diff < 60) return "in wenigen Sek.";
        if (diff < 3600) return `in ${Math.floor(diff / 60)} Min.`;
        if (diff < 86400) {
            const h = Math.floor(diff / 3600);
            const m = Math.floor((diff % 3600) / 60);
            return m > 0 ? `in ${h} Std. ${m} Min.` : `in ${h} Std.`;
        }
        return `in ${Math.floor(diff / 86400)} Tagen`;
    },

    formatTimestamp(unix) {
        if (!unix) return "Nie";
        const d = new Date(unix * 1000);
        return d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" })
            + " " + d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
    },

    formatDuration(seconds) {
        if (!seconds) return "-";
        if (seconds < 60) return `${seconds}s`;
        if (seconds < 3600) return `${Math.floor(seconds / 60)} Min.`;
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        return m > 0 ? `${h} Std. ${m} Min.` : `${h} Std.`;
    },
};

document.addEventListener("DOMContentLoaded", () => App.init());

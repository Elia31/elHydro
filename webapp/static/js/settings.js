// settings.js - Geräte-Einstellungen

const Settings = {
    mac: null,
    presets: [],

    async render(el, mac) {
        this.mac = mac;

        el.innerHTML = `<div class="loading"><div class="loader"><span></span><span></span><span></span></div></div>`;

        try {
            const [device, presets] = await Promise.all([
                App.api(`/devices/${encodeURIComponent(mac)}`),
                App.api("/plant-presets"),
            ]);
            this.presets = presets;

            const config = device.config || {};
            const name = device.name || mac;
            const isOutdoor = device.type === "outdoor";

            let presetOptions = presets.map(p =>
                `<option value="${this.esc(p.id)}" ${device.preset_id === p.id ? 'selected' : ''}>${this.esc(p.name)}</option>`
            ).join("");
            // Gelöschtes Preset trotzdem anzeigen, sonst würde beim Speichern
            // still das erste Preset übernommen
            if (!presets.some(p => p.id === device.preset_id)) {
                presetOptions = `<option value="${this.esc(device.preset_id || '')}" selected>Gelöschtes Preset</option>` + presetOptions;
            }

            el.innerHTML = `
                <div class="page-enter">
                    <div class="page-header">
                        <h1 class="page-title">
                            <svg><use href="#icon-settings"/></svg>
                            ${this.esc(name)}
                        </h1>
                        <button class="btn btn-outline btn-sm" onclick="App.navigate('/device/${encodeURIComponent(mac)}')">
                            <svg width="14" height="14"><use href="#icon-arrow-left"/></svg>
                            Zurück
                        </button>
                    </div>

                    <form id="settings-form" onsubmit="Settings.submit(event)" style="max-width:640px">

                        <div class="form-section">
                            <div class="form-section-title">
                                <svg><use href="#icon-leaf"/></svg>
                                Pflanze
                            </div>
                            <div class="form-group">
                                <label class="form-label">Pflanzentyp</label>
                                <select class="form-select" id="set-preset" onchange="Settings.onPresetChange()">
                                    ${presetOptions}
                                </select>
                            </div>
                            <div class="form-group">
                                <label class="form-label">Ziel-Bodenfeuchte: <strong id="target-label">${config.target_soil_pct ?? 50}%</strong></label>
                                <input class="form-range" type="range" id="set-target" min="10" max="90" step="1"
                                       value="${config.target_soil_pct ?? 50}"
                                       oninput="Settings.updateTarget()">
                            </div>
                            <div class="form-group">
                                <label class="form-label">Bewässerungs-Delta: <strong id="delta-label">${config.irrigation_start_delta ?? 10}%</strong></label>
                                <input class="form-range" type="range" id="set-irr-delta" min="5" max="50" step="1"
                                       value="${config.irrigation_start_delta ?? 10}"
                                       oninput="Settings.updateTarget()">
                                <div class="form-hint" id="threshold-hint"></div>
                                <div class="form-hint">Gilt online und offline — bei Hitze und Trockenheit auch früher</div>
                                <div id="delta-warning" class="form-hint" style="color:var(--warning);display:none"></div>
                            </div>
                        </div>

                        <div class="form-section">
                            <div class="form-section-title">
                                <svg><use href="#icon-clock"/></svg>
                                ESP32 Offline-Modus
                            </div>
                            <div class="form-hint" style="margin-bottom:0.75rem">Schlafzeit wenn der ESP32 keine Serververbindung hat</div>
                            <div class="form-group">
                                <label class="form-label">Offline Sleep: <strong id="offline-sleep-label">${App.formatDuration((config.offline_sleep_s ?? 14400))}</strong></label>
                                <input class="form-input" type="number" id="set-offline-sleep" min="10" max="1440"
                                       value="${Math.round((config.offline_sleep_s ?? 14400) / 60)}"
                                       oninput="Settings.updateSleepLabel('set-offline-sleep','offline-sleep-label')">
                                <div class="form-hint">Sleep-Dauer in Minuten (10 bis 1440)</div>
                            </div>
                        </div>

                        <div class="form-section">
                            <div class="form-section-title">
                                <svg><use href="#icon-sun"/></svg>
                                Standort
                            </div>
                            <div class="form-group">
                                <label class="form-label">Standort-Typ</label>
                                <div class="toggle-group" id="location-toggle">
                                    <button type="button" class="toggle-option ${!isOutdoor ? 'active' : ''}"
                                            onclick="Settings.setLocationType('indoor')">Indoor</button>
                                    <button type="button" class="toggle-option ${isOutdoor ? 'active' : ''}"
                                            onclick="Settings.setLocationType('outdoor')">Outdoor</button>
                                </div>
                                <input type="hidden" name="set-type" id="set-type-value" value="${isOutdoor ? 'outdoor' : 'indoor'}">
                            </div>
                            <div id="set-location-field" style="display:${isOutdoor ? 'block' : 'none'}">
                                <div class="form-group">
                                    <label class="form-label">Standort</label>
                                    <input class="form-input" id="set-location"
                                           value="${this.esc(device.location || '')}"
                                           placeholder="Stadt oder Koordinaten (z.B. Berlin oder 52.52,13.40)">
                                    <div class="form-hint">Für Wettervorhersage (Regen, Temperatur)</div>
                                </div>
                            </div>
                        </div>

                        <div style="display:flex;gap:0.5rem;margin-top:0.5rem">
                            <button type="submit" class="btn btn-primary">
                                <svg width="16" height="16"><use href="#icon-check"/></svg>
                                Speichern
                            </button>
                            <button type="button" class="btn btn-outline"
                                    onclick="App.navigate('/device/${encodeURIComponent(mac)}')">Abbrechen</button>
                        </div>
                    </form>
                </div>
            `;
            this.updateTarget();
        } catch (e) {
            el.innerHTML = `<p style="color:var(--danger)">Fehler: ${e.message}</p>
                <a href="/" class="btn btn-outline btn-sm" style="margin-top:1rem" onclick="return App.link(event)">Zurück</a>`;
        }
    },

    setLocationType(type) {
        document.getElementById("set-type-value").value = type;
        document.querySelectorAll("#location-toggle .toggle-option").forEach(btn => {
            btn.classList.toggle("active", btn.textContent.trim().toLowerCase() === type);
        });
        document.getElementById("set-location-field").style.display = type === "outdoor" ? "block" : "none";
    },

    onPresetChange() {
        const selected = document.getElementById("set-preset").value;
        const preset = this.presets.find(p => p.id === selected);
        if (preset && preset.id !== "custom") {
            document.getElementById("set-target").value = preset.target_soil_pct;
            if (preset.irrigation_start_delta != null) {
                document.getElementById("set-irr-delta").value = preset.irrigation_start_delta;
            }
            this.updateTarget();
        }
    },

    calcThreshold(target, delta) {
        // Gleiche Formel wie Firmware + Brain:
        // max(target - delta, target * 20%, 5%)
        const targetMin = Math.max(Math.floor(target * 0.2), 5);
        return Math.max(target - delta, targetMin);
    },

    updateTarget() {
        const targetEl = document.getElementById("set-target");
        const deltaEl = document.getElementById("set-irr-delta");
        const target = parseInt(targetEl.value) || 50;
        const delta = parseInt(deltaEl.value) || 10;
        const threshold = this.calcThreshold(target, delta);
        const rawThreshold = target - delta;

        document.getElementById("target-label").textContent = target + "%";
        document.getElementById("delta-label").textContent = delta + "%";

        const hintEl = document.getElementById("threshold-hint");
        hintEl.innerHTML = `Bewässerung startet spätestens bei <strong>${threshold}%</strong> Bodenfeuchte`;

        this.updateRangeFill(targetEl);
        this.updateRangeFill(deltaEl);

        const warn = document.getElementById("delta-warning");
        if (rawThreshold < threshold) {
            warn.textContent = `Delta zu groß - wird automatisch auf ${threshold}% begrenzt (mind. 20% vom Ziel)`;
            warn.style.display = "block";
        } else {
            warn.style.display = "none";
        }
    },

    updateSleepLabel(inputId, labelId) {
        const minutes = parseInt(document.getElementById(inputId).value) || 0;
        document.getElementById(labelId).textContent = App.formatDuration(minutes * 60);
    },

    updateRangeFill(el) {
        const pct = ((el.value - el.min) / (el.max - el.min)) * 100;
        el.style.background = `linear-gradient(to right, var(--primary) ${pct}%, var(--border) ${pct}%)`;
    },

    async submit(event) {
        event.preventDefault();

        const locationType = document.getElementById("set-type-value").value;
        const isOutdoor = locationType === "outdoor";
        const locationValue = isOutdoor ? document.getElementById("set-location").value.trim() : null;

        if (isOutdoor && !locationValue) {
            App.showToast("Bitte Standort für Outdoor-Gerät angeben", "warning");
            return;
        }

        const body = {
            target_soil_pct: parseInt(document.getElementById("set-target").value),
            irrigation_start_delta: parseInt(document.getElementById("set-irr-delta").value),
            offline_sleep_s: parseInt(document.getElementById("set-offline-sleep").value) * 60,
            preset_id: document.getElementById("set-preset").value || null,
            type: locationType,
            location: locationValue,
        };

        try {
            await App.api(`/devices/${encodeURIComponent(this.mac)}/settings`, {
                method: "PUT",
                body: JSON.stringify(body),
            });
            App.showToast("Einstellungen gespeichert! Werden beim nächsten Sync übertragen.", "success");
            App.navigate(`/device/${encodeURIComponent(this.mac)}`);
        } catch (e) {
            App.showToast(`Fehler: ${e.message}`, "danger");
        }
    },

    esc(str) {
        return App.esc(str);
    },
};

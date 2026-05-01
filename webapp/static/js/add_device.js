// add_device.js - BLE Scan + Geräte-Registrierung

const AddDevice = {
    selectedMac: null,
    selectedName: null,
    presets: [],

    async render(el) {
        this.selectedMac = null;
        this.selectedName = null;

        try {
            this.presets = await App.api("/plant-presets");
        } catch (e) {
            this.presets = [];
        }

        const presetOptions = this.presets
            .map(p => `<option value="${this.esc(p.name)}">${this.esc(p.name)}</option>`)
            .join("");

        el.innerHTML = `
            <div class="page-enter">
                <div class="page-header">
                    <h1 class="page-title">
                        <svg><use href="#icon-plus"/></svg>
                        Gerät hinzufügen
                    </h1>
                    <a href="/" class="btn btn-outline btn-sm" onclick="return App.link(event)">
                        <svg width="14" height="14"><use href="#icon-arrow-left"/></svg>
                        Zurück
                    </a>
                </div>

                <!-- Stepper -->
                <div class="stepper">
                    <div class="stepper-step active" id="step-1">
                        <span class="stepper-num">1</span>
                        Gerät wählen
                    </div>
                    <div class="stepper-line" id="step-line-1"></div>
                    <div class="stepper-step" id="step-2">
                        <span class="stepper-num">2</span>
                        Konfigurieren
                    </div>
                    <div class="stepper-line" id="step-line-2"></div>
                    <div class="stepper-step" id="step-3">
                        <span class="stepper-num">3</span>
                        Registrieren
                    </div>
                </div>

                <div class="two-col">
                    <div class="form-section">
                        <div class="form-section-title">
                            <svg><use href="#icon-zap"/></svg>
                            Gefundene Geräte
                        </div>
                        <p style="font-size:0.82rem;color:var(--text-muted);margin-bottom:0.75rem">
                            Scanne nach elHydro-Geräten in der Nähe...
                        </p>
                        <ul class="scan-list" id="scan-list">
                            <li class="loading" style="padding:1.5rem"><div class="loader"><span></span><span></span><span></span></div></li>
                        </ul>
                    </div>

                    <div class="form-section">
                        <div class="form-section-title">
                            <svg><use href="#icon-settings"/></svg>
                            Gerät registrieren
                        </div>
                        <form id="add-form" onsubmit="AddDevice.submit(event)">
                            <div class="form-group">
                                <label class="form-label">MAC-Adresse</label>
                                <input class="form-input" id="add-mac" readonly placeholder="Gerät aus Liste wählen..."
                                       style="font-family:monospace;letter-spacing:0.02em">
                            </div>
                            <div class="form-group">
                                <label class="form-label">Name</label>
                                <input class="form-input" id="add-name" required placeholder="z.B. Balkon-Tomate">
                            </div>
                            <div class="form-group">
                                <label class="form-label">Pflanzentyp</label>
                                <select class="form-select" id="add-plant-type">
                                    ${presetOptions}
                                </select>
                            </div>
                            <div class="form-group">
                                <label class="form-label">Standort</label>
                                <div class="toggle-group" id="add-location-toggle">
                                    <button type="button" class="toggle-option active"
                                            onclick="AddDevice.setLocationType('indoor')">Indoor</button>
                                    <button type="button" class="toggle-option"
                                            onclick="AddDevice.setLocationType('outdoor')">Outdoor</button>
                                </div>
                                <input type="hidden" id="add-type-value" value="indoor">
                                <div id="location-field" style="display:none;margin-top:0.75rem">
                                    <input class="form-input" id="add-location"
                                           placeholder="Stadt oder Koordinaten (z.B. Berlin oder 52.52,13.40)">
                                    <div class="form-hint">
                                        Wird für Wettervorhersage verwendet (Regen, Temperatur)
                                    </div>
                                </div>
                            </div>
                            <button type="submit" class="btn btn-primary" id="add-submit" disabled>
                                <svg width="16" height="16"><use href="#icon-check"/></svg>
                                Gerät registrieren
                            </button>
                        </form>
                    </div>
                </div>
            </div>
        `;

        // Bestehende Scan-Ergebnisse sofort anzeigen
        const list = document.getElementById("scan-list");
        if (App.state.scanResults.length > 0) {
            list.innerHTML = "";
            App.state.scanResults.forEach(d => this._addToList(d));
        }
    },

    setLocationType(type) {
        document.getElementById("add-type-value").value = type;
        document.querySelectorAll("#add-location-toggle .toggle-option").forEach(btn => {
            btn.classList.toggle("active", btn.textContent.trim().toLowerCase() === type);
        });
        document.getElementById("location-field").style.display = type === "outdoor" ? "block" : "none";
    },

    onDeviceFound(data) {
        const list = document.getElementById("scan-list");
        if (!list) return;

        const loading = list.querySelector(".loading");
        if (loading) loading.remove();

        this._addToList(data);
    },

    _addToList(data) {
        const list = document.getElementById("scan-list");
        if (!list) return;

        const existing = list.querySelector(`[data-mac="${data.mac}"]`);
        if (existing) {
            existing.querySelector(".scan-rssi").textContent = `${data.rssi} dBm`;
            return;
        }

        const li = document.createElement("li");
        li.className = "scan-item";
        li.dataset.mac = data.mac;
        li.innerHTML = `
            <div>
                <strong>${this.esc(data.name)}</strong>
                <div style="font-size:0.78rem;color:var(--text-muted);font-family:monospace;letter-spacing:0.02em">${data.mac}</div>
            </div>
            <span class="scan-rssi">${data.rssi} dBm</span>
        `;
        li.onclick = () => this.selectDevice(data.mac, data.name);
        list.appendChild(li);
    },

    selectDevice(mac, name) {
        this.selectedMac = mac;
        this.selectedName = name;

        document.getElementById("add-mac").value = mac;
        document.getElementById("add-name").value = name || "";
        document.getElementById("add-submit").disabled = false;

        // Selection-Highlight
        document.querySelectorAll(".scan-item").forEach(el => {
            el.classList.toggle("selected", el.dataset.mac === mac);
        });

        // Update stepper
        document.getElementById("step-2").classList.add("active");
        document.getElementById("step-line-1").classList.add("active");
    },

    async submit(event) {
        event.preventDefault();

        const mac = document.getElementById("add-mac").value;
        const name = document.getElementById("add-name").value.trim();
        const plantType = document.getElementById("add-plant-type").value;
        const locationType = document.getElementById("add-type-value").value;
        const isOutdoor = locationType === "outdoor";
        const loc = isOutdoor ? document.getElementById("add-location").value.trim() : null;

        if (!mac || !name) {
            App.showToast("Bitte Gerät wählen und Name eingeben", "warning");
            return;
        }

        if (isOutdoor && !loc) {
            App.showToast("Bitte Standort für Outdoor-Gerät angeben", "warning");
            return;
        }

        // Update stepper
        document.getElementById("step-3").classList.add("active");
        document.getElementById("step-line-2").classList.add("active");

        try {
            await App.api("/devices", {
                method: "POST",
                body: JSON.stringify({ mac, name, plant_type: plantType, is_outdoor: isOutdoor, location: loc }),
            });
            App.showToast(`${name} erfolgreich registriert!`, "success");
            App.navigate("/");
        } catch (e) {
            App.showToast(`Fehler: ${e.message}`, "danger");
        }
    },

    esc(str) {
        const d = document.createElement("div");
        d.textContent = str || "";
        return d.innerHTML;
    },
};

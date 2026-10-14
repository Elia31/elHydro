// preset_editor.js - Globaler Pflanzen-Preset-Editor

const PresetEditor = {
    presets: [],

    async render(el) {
        el.innerHTML = `<div class="loading"><div class="loader"><span></span><span></span><span></span></div></div>`;

        try {
            this.presets = await App.api("/plant-presets");

            el.innerHTML = `
                <div class="page-enter">
                    <div class="page-header">
                        <h1 class="page-title">
                            <svg><use href="#icon-sliders"/></svg>
                            Pflanzen-Presets
                        </h1>
                        <button class="btn btn-outline btn-sm" onclick="App.navigate('/')">
                            <svg width="14" height="14"><use href="#icon-arrow-left"/></svg>
                            Zurück
                        </button>
                    </div>

                    <div style="max-width:720px">
                        <div class="preset-table-wrapper">
                        <table class="preset-table" id="preset-table">
                            <thead>
                                <tr>
                                    <th>Pflanze</th>
                                    <th>Ziel (%)</th>
                                    <th>Delta (%)</th>
                                    <th>Sleep-Faktor</th>
                                    <th style="width:36px"></th>
                                </tr>
                            </thead>
                            <tbody>
                                ${this.rowsHtml()}
                            </tbody>
                        </table>
                        </div>

                        <div style="display:flex;gap:0.5rem;margin-top:1.25rem">
                            <button class="btn btn-outline btn-sm" onclick="PresetEditor.addRow()">
                                <svg width="14" height="14"><use href="#icon-plus"/></svg>
                                Preset hinzufügen
                            </button>
                            <button class="btn btn-primary btn-sm" onclick="PresetEditor.save()">
                                <svg width="14" height="14"><use href="#icon-check"/></svg>
                                Speichern
                            </button>
                        </div>
                    </div>
                </div>
            `;
        } catch (e) {
            el.innerHTML = `<p style="color:var(--danger)">Fehler: ${e.message}</p>`;
        }
    },

    rowsHtml() {
        return this.presets.map((p, i) => `
            <tr data-idx="${i}">
                <td><input class="form-input" value="${this.esc(p.name)}" data-field="name" style="min-width:100px"></td>
                <td><input class="form-input" type="number" value="${p.target_soil_pct}" data-field="target_soil_pct" min="10" max="90" style="width:60px"></td>
                <td><input class="form-input" type="number" value="${p.irrigation_start_delta ?? 10}" data-field="irrigation_start_delta" min="5" max="50" step="1" style="width:60px"></td>
                <td><input class="form-input" type="number" value="${p.sleep_multiplier}" data-field="sleep_multiplier" min="0.1" max="5" step="0.05" style="width:60px"></td>
                <td>
                    <button class="btn-delete-row" onclick="PresetEditor.removeRow(${i})" title="Entfernen">
                        <svg><use href="#icon-trash"/></svg>
                    </button>
                </td>
            </tr>
        `).join("");
    },

    addRow() {
        this.collectFromDom();
        const id = "custom_" + Date.now();
        this.presets.push({
            id: id,
            name: "Neues Preset",
            target_soil_pct: 50,
            sleep_multiplier: 1.0,
            irrigation_start_delta: 10,
        });
        document.querySelector("#preset-table tbody").innerHTML = this.rowsHtml();
    },

    removeRow(idx) {
        this.collectFromDom();
        if (this.presets.length <= 1) {
            App.showToast("Mindestens ein Preset muss vorhanden sein", "warning");
            return;
        }
        this.presets.splice(idx, 1);
        document.querySelector("#preset-table tbody").innerHTML = this.rowsHtml();
    },

    collectFromDom() {
        const rows = document.querySelectorAll("#preset-table tbody tr");
        rows.forEach((row, i) => {
            if (i < this.presets.length) {
                const nameInput = row.querySelector('[data-field="name"]');
                const targetInput = row.querySelector('[data-field="target_soil_pct"]');
                const deltaInput = row.querySelector('[data-field="irrigation_start_delta"]');
                const multInput = row.querySelector('[data-field="sleep_multiplier"]');
                if (nameInput) this.presets[i].name = nameInput.value;
                if (targetInput) this.presets[i].target_soil_pct = parseInt(targetInput.value) || 50;
                if (deltaInput) this.presets[i].irrigation_start_delta = parseInt(deltaInput.value) || 10;
                if (multInput) this.presets[i].sleep_multiplier = parseFloat(multInput.value) || 1.0;
            }
        });
    },

    async save() {
        this.collectFromDom();

        for (const p of this.presets) {
            if (!p.name.trim()) {
                App.showToast("Preset-Name darf nicht leer sein", "warning");
                return;
            }
        }

        try {
            await App.api("/plant-presets", {
                method: "PUT",
                body: JSON.stringify(this.presets),
            });
            App.showToast("Presets gespeichert!", "success");
        } catch (e) {
            App.showToast(`Fehler: ${e.message}`, "danger");
        }
    },

    esc(str) {
        return App.esc(str);
    },
};

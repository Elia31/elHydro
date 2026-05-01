// logs.js - Log-Viewer
const Logs = {
    container: null,
    autoScroll: true,

    async render(el) {
        this.container = el;
        el.innerHTML = `
            <div class="page-enter">
                <div class="page-header">
                    <h1 class="page-title">
                        <svg><use href="#icon-info"/></svg>
                        Logs
                    </h1>
                    <div style="display:flex;gap:0.5rem;flex-wrap:wrap;align-items:center">
                        <select id="log-filter-mac" class="form-select" onchange="Logs.reload()">
                            <option value="">Alle Geräte</option>
                        </select>
                        <select id="log-filter-level" class="form-select" onchange="Logs.reload()">
                            <option value="">Alle Level</option>
                            <option value="INFO">INFO</option>
                            <option value="WARNING">WARNING</option>
                            <option value="ERROR">ERROR</option>
                        </select>
                        <label class="log-auto-label">
                            <input type="checkbox" id="log-autoscroll" checked onchange="Logs.autoScroll = this.checked"> Live
                        </label>
                    </div>
                </div>
                <div class="log-table-wrapper" id="log-table-wrapper">
                    <table class="log-table">
                        <thead>
                            <tr>
                                <th style="width:140px">Zeitstempel</th>
                                <th style="width:60px">Level</th>
                                <th style="width:140px">Gerät</th>
                                <th>Nachricht</th>
                            </tr>
                        </thead>
                        <tbody id="log-tbody">
                        </tbody>
                    </table>
                </div>
            </div>
        `;

        await this.populateDeviceFilter();
        await this.reload();
    },

    async populateDeviceFilter() {
        try {
            const devices = await App.api("/devices");
            const select = document.getElementById("log-filter-mac");
            if (!select) return;
            devices.forEach(d => {
                const opt = document.createElement("option");
                opt.value = d.mac;
                opt.textContent = d.name || d.mac;
                select.appendChild(opt);
            });
        } catch (e) { /* ignore */ }
    },

    async reload() {
        const mac = document.getElementById("log-filter-mac")?.value || "";
        const level = document.getElementById("log-filter-level")?.value || "";
        let url = "/logs?limit=500";
        if (mac) url += `&mac=${encodeURIComponent(mac)}`;
        if (level) url += `&level=${encodeURIComponent(level)}`;

        try {
            const logs = await App.api(url);
            const tbody = document.getElementById("log-tbody");
            if (!tbody) return;

            tbody.innerHTML = logs.slice().reverse().map(entry => this.rowHtml(entry)).join("");

            if (this.autoScroll) {
                const wrapper = document.getElementById("log-table-wrapper");
                if (wrapper) wrapper.scrollTop = 0;
            }
        } catch (e) {
            App.showToast(`Logs laden fehlgeschlagen: ${e.message}`, "danger");
        }
    },

    rowHtml(entry) {
        const ts = entry.ts ? App.formatTimestamp(entry.ts) : "-";
        const levelCls = {
            INFO: "log-info",
            WARNING: "log-warn",
            ERROR: "log-error",
        }[entry.level] || "log-info";

        return `<tr>
            <td class="log-ts">${ts}</td>
            <td><span class="log-level ${levelCls}">${entry.level || "INFO"}</span></td>
            <td class="log-mac">${entry.mac || "-"}</td>
            <td>${this.esc(entry.msg || "")}</td>
        </tr>`;
    },

    onLogReceived(data) {
        if (App.currentView !== "logs") return;
        const tbody = document.getElementById("log-tbody");
        if (!tbody) return;

        const filterMac = document.getElementById("log-filter-mac")?.value || "";
        const filterLevel = document.getElementById("log-filter-level")?.value || "";
        if (filterMac && data.mac !== filterMac) return;
        if (filterLevel && (data.level || "INFO") !== filterLevel) return;

        const entry = {
            ts: Math.floor(Date.now() / 1000),
            level: data.level || "INFO",
            mac: data.mac || null,
            msg: data.message || "",
        };
        tbody.insertAdjacentHTML("afterbegin", this.rowHtml(entry));

        if (this.autoScroll) {
            const wrapper = document.getElementById("log-table-wrapper");
            if (wrapper) wrapper.scrollTop = 0;
        }
    },

    esc(str) {
        const d = document.createElement("div");
        d.textContent = str || "";
        return d.innerHTML;
    },
};

const elements = {
    apiStatus: document.getElementById("api-status"),
    mqttStatus: document.getElementById("mqtt-status"),
    lastUpdated: document.getElementById("last-updated"),
    tagCount: document.getElementById("tag-count"),
    alertCount: document.getElementById("alert-count"),
    tagList: document.getElementById("tag-list"),
    alertsList: document.getElementById("alerts-list"),
    mapOverlay: document.getElementById("map-overlay"),
    tagTemplate: document.getElementById("tag-card-template"),
    alertTemplate: document.getElementById("alert-item-template")
};

const REFRESH_INTERVAL_MS = 10000;

function createEmptyState(title, message) {
    const article = document.createElement("article");
    const heading = document.createElement("h3");
    const body = document.createElement("p");

    article.className = "empty-state";
    heading.textContent = title;
    body.textContent = message;

    article.append(heading, body);
    return article;
}

function formatValue(value, fallback = "N/A") {
    return value === null || value === undefined || value === "" ? fallback : value;
}

function formatTemperature(value) {
    return value === null || value === undefined ? "N/A" : `${Number(value).toFixed(1)} C`;
}

function formatBattery(value) {
    return value === null || value === undefined ? "N/A" : `${Math.round(Number(value))}%`;
}

function formatTime(value) {
    if (!value) {
        return "Unknown";
    }

    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "Unknown" : date.toLocaleString();
}

function deriveStatus(item) {
    const battery = Number(item.battery);
    const temperature = Number(item.temperature);

    if (!Number.isNaN(battery) && battery <= 20) {
        return { label: "critical", css: "critical" };
    }

    if (!Number.isNaN(temperature) && temperature >= 8) {
        return { label: "warning", css: "warning" };
    }

    if (item.moving) {
        return { label: "moving", css: "moving" };
    }

    return { label: "stable", css: "stable" };
}

function medicineLabel(item) {
    return item.medicine || `Tag ${String(item.mac || "Unknown").slice(-4)}`;
}

function renderTagList(items) {
    elements.tagCount.textContent = `${items.length} tag${items.length === 1 ? "" : "s"}`;
    elements.tagList.innerHTML = "";

    if (!items.length) {
        elements.tagList.appendChild(createEmptyState(
            "No tag data yet",
            "Waiting for medicine telemetry from the backend."
        ));
        return;
    }

    const fragment = document.createDocumentFragment();

    items.forEach((item) => {
        const status = deriveStatus(item);
        const clone = elements.tagTemplate.content.cloneNode(true);
        clone.querySelector(".tag-name").textContent = medicineLabel(item);
        clone.querySelector(".tag-mac").textContent = formatValue(item.mac, "Unknown tag");

        const badge = clone.querySelector(".status-badge");
        badge.textContent = status.label;
        badge.classList.add(`status-${status.css}`);

        clone.querySelector(".battery").textContent = formatBattery(item.battery);
        clone.querySelector(".temperature").textContent = formatTemperature(item.temperature);
        clone.querySelector(".receiver").textContent = formatValue(item.receiver_id);
        clone.querySelector(".updated").textContent = formatTime(item.time);
        fragment.appendChild(clone);
    });

    elements.tagList.appendChild(fragment);
}

function markerPosition(item, index) {
    const key = `${item.receiver_id || "receiver"}-${item.mac || index}`;
    let hash = 0;

    for (let i = 0; i < key.length; i += 1) {
        hash = ((hash << 5) - hash) + key.charCodeAt(i);
        hash |= 0;
    }

    const x = 18 + (Math.abs(hash) % 64);
    const y = 18 + (Math.abs(hash * 7) % 58);
    return { x, y };
}

function renderMap(items) {
    elements.mapOverlay.innerHTML = "";

    const fragment = document.createDocumentFragment();

    items.slice(0, 12).forEach((item, index) => {
        const status = deriveStatus(item);
        const position = markerPosition(item, index);
        const marker = document.createElement("div");
        const dot = document.createElement("span");
        const label = document.createElement("span");

        marker.className = "map-marker";
        marker.style.left = `${position.x}%`;
        marker.style.top = `${position.y}%`;

        dot.className = `map-marker-dot dot-${status.css}`;
        label.className = "map-marker-label";
        label.textContent = medicineLabel(item);

        marker.append(dot, label);
        fragment.appendChild(marker);
    });

    elements.mapOverlay.appendChild(fragment);
}

function renderAlerts(items) {
    elements.alertCount.textContent = `${items.length} alert${items.length === 1 ? "" : "s"}`;
    elements.alertsList.innerHTML = "";

    if (!items.length) {
        elements.alertsList.appendChild(createEmptyState(
            "No alerts yet",
            "Recent alert records from InfluxDB will appear here."
        ));
        return;
    }

    const fragment = document.createDocumentFragment();

    items.forEach((item) => {
        const clone = elements.alertTemplate.content.cloneNode(true);
        const severity = String(item.severity || "info").toLowerCase();
        const severityNode = clone.querySelector(".alert-severity");

        severityNode.textContent = severity;
        severityNode.classList.add(`severity-${severity}`);
        clone.querySelector(".alert-time").textContent = formatTime(item.time);
        clone.querySelector(".alert-title").textContent = item.medicine || item.alert_type || "System alert";
        clone.querySelector(".alert-message").textContent = item.message || "No alert details available.";
        fragment.appendChild(clone);
    });

    elements.alertsList.appendChild(fragment);
}

async function fetchJson(url) {
    const response = await fetch(url);

    if (!response.ok) {
        throw new Error(`${url} returned ${response.status}`);
    }

    return response.json();
}

async function refreshDashboard() {
    try {
        const [medicines, alerts, status] = await Promise.all([
            fetchJson("/api/medicines"),
            fetchJson("/api/alerts?hours=24"),
            fetchJson("/api/status")
        ]);

        elements.apiStatus.textContent = "Online";
        elements.mqttStatus.textContent = status.mqtt_connected ? "Connected" : "Offline";
        elements.lastUpdated.textContent = new Date().toLocaleTimeString();

        const normalizedMedicines = Array.isArray(medicines) ? medicines : [];
        const normalizedAlerts = Array.isArray(alerts) ? alerts.slice(0, 12) : [];

        renderTagList(normalizedMedicines);
        renderMap(normalizedMedicines);
        renderAlerts(normalizedAlerts);
    } catch (error) {
        elements.apiStatus.textContent = "Error";
        elements.mqttStatus.textContent = "Unknown";
        elements.lastUpdated.textContent = "Refresh failed";

        const message = error instanceof Error ? error.message : "Unknown error";
        elements.tagList.innerHTML = "";
        elements.alertsList.innerHTML = "";
        elements.tagList.appendChild(createEmptyState("Unable to load dashboard data", message));
        elements.alertsList.appendChild(createEmptyState("Alert feed unavailable", message));
        elements.mapOverlay.innerHTML = "";
    }
}

refreshDashboard();
window.setInterval(refreshDashboard, REFRESH_INTERVAL_MS);
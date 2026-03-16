import { useState, useEffect } from 'react'

const REFRESH_INTERVAL_MS = 10000;

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
    if (!value) return "Unknown";
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

const EmptyState = ({ title, message }) => (
    <article className="empty-state">
        <h3>{title}</h3>
        <p>{message}</p>
    </article>
);

const TagCard = ({ item }) => {
    const status = deriveStatus(item);
    return (
        <article className="tag-card">
            <div className="tag-card-head">
                <div>
                    <h3 className="tag-name">{medicineLabel(item)}</h3>
                    <p className="tag-mac">{formatValue(item.mac, "Unknown tag")}</p>
                </div>
                <span className={`status-badge status-${status.css}`}>{status.label}</span>
            </div>
            <dl className="tag-metrics">
                <div>
                    <dt>Battery</dt>
                    <dd className="battery">{formatBattery(item.battery)}</dd>
                </div>
                <div>
                    <dt>Temperature</dt>
                    <dd className="temperature">{formatTemperature(item.temperature)}</dd>
                </div>
                <div>
                    <dt>Receiver</dt>
                    <dd className="receiver">{formatValue(item.receiver_id)}</dd>
                </div>
                <div>
                    <dt>Updated</dt>
                    <dd className="updated">{formatTime(item.time)}</dd>
                </div>
            </dl>
        </article>
    );
};

const AlertItem = ({ item }) => {
    const severity = String(item.severity || "info").toLowerCase();
    return (
        <article className="alert-item">
            <div className="alert-item-head">
                <span className={`alert-severity severity-${severity}`}>{severity}</span>
                <time className="alert-time">{formatTime(item.time)}</time>
            </div>
            <h3 className="alert-title">{item.medicine || item.alert_type || "System alert"}</h3>
            <p className="alert-message">{item.message || "No alert details available."}</p>
        </article>
    );
};

function App() {
    const [medicines, setMedicines] = useState([]);
    const [alerts, setAlerts] = useState([]);
    const [status, setStatus] = useState({ mqtt_connected: false });
    const [apiState, setApiState] = useState("Connecting");
    const [lastRefresh, setLastRefresh] = useState("Waiting for data");

    const fetchData = async () => {
        try {
            const [medRes, alertRes, statusRes] = await Promise.all([
                fetch("/api/medicines"),
                fetch("/api/alerts?hours=24"),
                fetch("/api/status")
            ]);

            if (!medRes.ok || !alertRes.ok || !statusRes.ok) throw new Error("API response not OK");

            const medData = await medRes.json();
            const alertData = await alertRes.json();
            const statusData = await statusRes.json();

            setMedicines(Array.isArray(medData) ? medData : []);
            setAlerts(Array.isArray(alertData) ? alertData.slice(0, 12) : []);
            setStatus(statusData);
            setApiState("Online");
            setLastRefresh(new Date().toLocaleTimeString());
        } catch (error) {
            setApiState("Error");
            setLastRefresh("Refresh failed");
            console.error(error);
        }
    };

    useEffect(() => {
        fetchData();
        const timer = setInterval(fetchData, REFRESH_INTERVAL_MS);
        return () => clearInterval(timer);
    }, []);

    return (
        <div className="app-shell">
            <header className="topbar">
                <div>
                    <p className="eyebrow">Hospital Monitoring Console</p>
                    <h1>Medical Tracker Dashboard</h1>
                </div>
                <div className="status-strip">
                    <div className="status-chip">
                        <span className="label">API</span>
                        <strong>{apiState}</strong>
                    </div>
                    <div className="status-chip">
                        <span className="label">MQTT</span>
                        <strong>{status.mqtt_connected ? "Connected" : "Offline"}</strong>
                    </div>
                    <div className="status-chip wide">
                        <span className="label">Last refresh</span>
                        <strong>{lastRefresh}</strong>
                    </div>
                </div>
            </header>

            <main className="dashboard-grid">
                <section className="panel tag-panel">
                    <div className="panel-heading">
                        <div>
                            <p className="panel-kicker">Inventory</p>
                            <h2>Medicine Tags</h2>
                        </div>
                        <span className="count-pill">{medicines.length} tags</span>
                    </div>
                    <div className="tag-list">
                        {medicines.length === 0 ? (
                            <EmptyState 
                                title="No tag data yet" 
                                message="Waiting for medicine telemetry from the backend." 
                            />
                        ) : (
                            medicines.map((item, idx) => (
                                <TagCard key={item.mac || idx} item={item} />
                            ))
                        )}
                    </div>
                </section>

                <section className="panel map-panel">
                    <div className="panel-heading">
                        <div>
                            <p className="panel-kicker">Location</p>
                            <h2>Ward Floor Map</h2>
                        </div>
                        <span className="map-caption">Placeholder image with live overlays</span>
                    </div>
                    <div className="map-stage">
                        <img src="/assets/floor-map-placeholder.svg" alt="Placeholder hospital floor map" className="floor-map-image" />
                        <div className="map-overlay">
                            {medicines.slice(0, 12).map((item, index) => {
                                const pos = markerPosition(item, index);
                                const itemStatus = deriveStatus(item);
                                return (
                                    <div key={item.mac || index} className="map-marker" style={{ left: `${pos.x}%`, top: `${pos.y}%` }}>
                                        <span className={`map-marker-dot dot-${itemStatus.css}`}></span>
                                        <span className="map-marker-label">{medicineLabel(item)}</span>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                    <div className="map-legend">
                        <span><i className="legend-dot stable"></i> Stable</span>
                        <span><i className="legend-dot moving"></i> Moving</span>
                        <span><i className="legend-dot warning"></i> Needs attention</span>
                    </div>
                </section>

                <section className="panel alerts-panel">
                    <div className="panel-heading">
                        <div>
                            <p className="panel-kicker">Events</p>
                            <h2>Alert Feed</h2>
                        </div>
                        <span className="count-pill">{alerts.length} alerts</span>
                    </div>
                    <div className="alerts-list">
                        {alerts.length === 0 ? (
                            <EmptyState 
                                title="No alerts yet" 
                                message="Recent alert records from InfluxDB will appear here." 
                            />
                        ) : (
                            alerts.map((item, idx) => (
                                <AlertItem key={idx} item={item} />
                            ))
                        )}
                    </div>
                </section>
            </main>
        </div>
    );
}

export default App

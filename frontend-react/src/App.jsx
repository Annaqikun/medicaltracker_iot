import { useEffect, useState } from 'react';

const REFRESH_INTERVAL_MS = 10000;
const WORLD_MIN_X = 0;
const WORLD_MAX_X = 10;
const WORLD_MIN_Y = 0;
const WORLD_MAX_Y = 8.66;
const FLIP_Y_AXIS = false;

function formatBattery(value) {
    if (value === null || value === undefined) return 'N/A';
    return `${Math.round(Number(value))}%`;
}

function deriveStatus(item) {
    const battery = Number(item.battery);
    const temperature = Number(item.temperature);

    if (!Number.isNaN(battery) && battery <= 20) return { label: 'critical', css: 'critical' };
    if (!Number.isNaN(temperature) && temperature >= 8) return { label: 'warning', css: 'warning' };
    if (item.moving) return { label: 'moving', css: 'moving' };
    return { label: 'stable', css: 'stable' };
}

function medicineLabel(item) {
    return item?.medicine || `Tag ${String(item?.mac || 'Unknown').slice(-4)}`;
}

function markerPosition(item, index) {
    const key = `${item.receiver_id || 'receiver'}-${item.mac || index}`;
    let hash = 0;
    for (let i = 0; i < key.length; i += 1) {
        hash = ((hash << 5) - hash) + key.charCodeAt(i);
        hash |= 0;
    }
    const x = 16 + (Math.abs(hash) % 68);
    const y = 16 + (Math.abs(hash * 7) % 62);
    return { x, y };
}

function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
}

function worldToMapPercent(x, y) {
    const normalizedX = (Number(x) - WORLD_MIN_X) / (WORLD_MAX_X - WORLD_MIN_X);
    const normalizedY = (Number(y) - WORLD_MIN_Y) / (WORLD_MAX_Y - WORLD_MIN_Y);
    const left = clamp(normalizedX * 100, 0, 100);
    const top = clamp((FLIP_Y_AXIS ? 1 - normalizedY : normalizedY) * 100, 0, 100);
    return { x: left, y: top };
}

async function fetchPositionsWithFallback() {
    const primary = await fetch('/api/positions');
    if (primary.ok) return primary.json();

    const fallback = await fetch('/api/medicines/positions');
    if (fallback.ok) {
        const fallbackData = await fallback.json();
        if (Array.isArray(fallbackData)) {
            return fallbackData
                .map((item) => item?.position)
                .filter((item) => item && item.mac);
        }
    }

    throw new Error('No valid positions endpoint available');
}

const TagCard = ({ item }) => {
    const status = deriveStatus(item);
    return (
        <article className="tag-card">
            <div className="tag-card-row">
                <div className="tag-main-name">{medicineLabel(item)}</div>
                <div className="tag-chevron">v</div>
            </div>
            <div className="tag-card-meta">{String(item.mac || '').toLowerCase()}</div>
            <div className={`tag-status tag-status-${status.css}`}>{status.label}</div>
            <div className="tag-battery">Battery {formatBattery(item.battery)}</div>
        </article>
    );
};

const MapZone = ({ title, subtitle, className }) => (
    <div className={`map-zone ${className}`}>
        <div className="map-zone-title">{title}</div>
        <div className="map-zone-subtitle">{subtitle}</div>
    </div>
);

function App() {
    const [medicines, setMedicines] = useState([]);
    const [positionsByMac, setPositionsByMac] = useState({});
    const [alerts, setAlerts] = useState([]);
    const [status, setStatus] = useState({ mqtt_connected: false });
    const [apiState, setApiState] = useState('Connecting');
    const [lastRefresh, setLastRefresh] = useState('Waiting');

    const fetchData = async () => {
        try {
            const [medRes, alertRes, statusRes, positionData] = await Promise.all([
                fetch('/api/medicines'),
                fetch('/api/alerts?hours=24'),
                fetch('/api/status'),
                fetchPositionsWithFallback(),
            ]);

            if (!medRes.ok || !alertRes.ok || !statusRes.ok) {
                throw new Error('API response not OK');
            }

            const [medData, alertData, statusData] = await Promise.all([
                medRes.json(),
                alertRes.json(),
                statusRes.json(),
            ]);

            const map = (Array.isArray(positionData) ? positionData : []).reduce((acc, pos) => {
                if (pos?.mac) acc[pos.mac] = pos;
                return acc;
            }, {});

            setMedicines(Array.isArray(medData) ? medData : []);
            setAlerts(Array.isArray(alertData) ? alertData : []);
            setStatus(statusData || { mqtt_connected: false });
            setPositionsByMac(map);
            setApiState('Online');
            setLastRefresh(new Date().toLocaleTimeString('en-US', {
                hour: 'numeric',
                minute: '2-digit',
                second: '2-digit',
                hour12: true,
            }));
        } catch (error) {
            setApiState('Error');
            setLastRefresh('Refresh failed');
            console.error(error);
        }
    };

    useEffect(() => {
        fetchData();
        const timer = setInterval(fetchData, REFRESH_INTERVAL_MS);
        return () => clearInterval(timer);
    }, []);

    const shownTags = medicines.slice(0, 8);
    const preventWheelTracking = (event) => event.preventDefault();

    return (
        <div className="page">
            <header className="topbar">
                <div className="brand-wrap">
                    <div className="brand-icon">S</div>
                    <div>
                        <div className="brand-overline">Hospital Monitoring Console</div>
                        <h1 className="brand-title">Medical Tracker Dashboard</h1>
                    </div>
                </div>

                <div className="topbar-stats">
                    <div className="stat-chip">
                        <div className="stat-label">API Status</div>
                        <div className={`stat-value ${apiState === 'Online' ? 'ok' : 'down'}`}>{apiState}</div>
                    </div>
                    <div className="stat-chip">
                        <div className="stat-label">MQTT</div>
                        <div className={`stat-value ${status?.mqtt_connected ? 'ok' : 'down'}`}>
                            {status?.mqtt_connected ? 'Connected' : 'Disconnected'}
                        </div>
                    </div>
                    <div className="stat-chip">
                        <div className="stat-label">Last Refresh</div>
                        <div className="stat-value neutral">{lastRefresh}</div>
                    </div>
                </div>
            </header>

            <main className="layout">
                <section className="panel inventory">
                    <div className="panel-head">
                        <div>
                            <div className="panel-kicker">Inventory</div>
                            <h2 className="panel-title">Medicine Tags</h2>
                        </div>
                        <div className="pill-green">{shownTags.length} active</div>
                    </div>

                    <div className="panel-body tags-list">
                        {shownTags.length === 0 && <div className="empty-hint">No tags available.</div>}
                        {shownTags.map((item, idx) => (
                            <TagCard key={item.mac || idx} item={item} />
                        ))}
                    </div>
                </section>

                <section className="panel map">
                    <div className="panel-head">
                        <div>
                            <div className="panel-kicker">Real-Time Location</div>
                            <h2 className="panel-title">Ward Floor Map</h2>
                        </div>
                    </div>

                    <div className="panel-body map-body" onWheel={preventWheelTracking}>
                        <div className="zone-grid">
                            <MapZone title="Cold Storage" subtitle="Refrigerated medications" className="zone-cold" />
                            <MapZone title="Nurse Prep" subtitle="Staging and handling" className="zone-nurse" />
                            <MapZone title="ICU Ward" subtitle="High priority medication area" className="zone-icu" />
                            <MapZone title="Storage A" subtitle="General supplies" className="zone-storage" />
                            <MapZone title="Main Corridor" subtitle="Live tag markers are visual placeholders until trilaterated coordinates are exposed" className="zone-corridor" />
                            <MapZone title="Pharmacy" subtitle="Dispensing area" className="zone-pharmacy" />

                            <div className="marker-layer">
                                {shownTags.map((m, idx) => {
                                    const position = positionsByMac[m.mac];
                                    const hasWorldPosition = position && Number.isFinite(Number(position.x)) && Number.isFinite(Number(position.y));
                                    const coord = hasWorldPosition ? worldToMapPercent(position.x, position.y) : markerPosition(m, idx);
                                    const state = deriveStatus(m);

                                    return (
                                        <div
                                            key={m.mac || idx}
                                            className="map-marker"
                                            style={{
                                                left: `${coord.x}%`,
                                                top: `${coord.y}%`,
                                                opacity: hasWorldPosition ? 1 : 0.75,
                                            }}
                                        >
                                            <span className={`dot dot-${state.css}`} />
                                            <span className="marker-label">{medicineLabel(m)}</span>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    </div>

                    <div className="legend-row">
                        <div className="legend-item"><span className="legend-dot lg-stable" />Stable</div>
                        <div className="legend-item"><span className="legend-dot lg-moving" />Moving</div>
                        <div className="legend-item"><span className="legend-dot lg-warning" />Needs Attention</div>
                    </div>
                </section>

                <section className="panel alerts">
                    <div className="panel-head">
                        <div>
                            <div className="panel-kicker">Event Monitor</div>
                            <h2 className="panel-title">Alert Feed</h2>
                        </div>
                        <div className="pill-gray">{alerts.length}</div>
                    </div>

                    <div className="panel-body alerts-body">
                        {alerts.length === 0 ? (
                            <div className="all-clear">
                                <div className="check-mark">OK</div>
                                <div className="clear-title">All Clear</div>
                                <div className="clear-subtitle">No alerts at this time. Monitoring active.</div>
                            </div>
                        ) : (
                            alerts.slice(0, 12).map((a, idx) => (
                                <article key={`${a.mac || 'alert'}-${idx}`} className="alert-item">
                                    <div className="alert-title-line">{a.medicine || a.alert_type || 'System alert'}</div>
                                    <div className="alert-copy">{a.message || 'No alert details available.'}</div>
                                </article>
                            ))
                        )}
                    </div>
                </section>
            </main>
        </div>
    );
}

export default App;

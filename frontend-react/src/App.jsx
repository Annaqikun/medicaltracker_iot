import { useEffect, useState } from 'react';

const REFRESH_INTERVAL_MS = 10000;
const WORLD_MIN_X = 0;
const WORLD_MAX_X = 10;
const WORLD_MIN_Y = 0;
const WORLD_MAX_Y = 10.0;
const FLIP_Y_AXIS = true;

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

/**
 * Generates a stable visual offset based on the MAC address
 * to prevent markers from stacking perfectly on top of each other.
 */
function getMarkerJitter(mac) {
    if (!mac) return { x: 0, y: 0 };
    let hash = 0;
    for (let i = 0; i < mac.length; i++) {
        hash = ((hash << 5) - hash) + mac.charCodeAt(i);
    }
    // Result is between -4 and +4 percent jitter - makes clusters much more visible
    const xJitter = (Math.abs(hash) % 80) / 10 - 4;
    const yJitter = (Math.abs(hash * 7) % 80) / 10 - 4;
    return { x: xJitter, y: yJitter };
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
    
    // Map 0-1 to a slightly inset range (4% to 96%) to prevent clipping at the edges
    const left = clamp(normalizedX * 92 + 4, 3, 97);
    const top = clamp((FLIP_Y_AXIS ? 1 - normalizedY : normalizedY) * 92 + 4, 3, 97);
    
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
    const [isBuzzing, setIsBuzzing] = useState(false);
    const status = deriveStatus(item);

    const handleFind = async () => {
        if (!item?.mac || isBuzzing) return;

        setIsBuzzing(true);
        setTimeout(() => setIsBuzzing(false), 5000);

        try {
            await fetch(`/api/medicine/${item.mac}/find`, {
                method: 'POST',
            });
        } catch (error) {
            console.error('Failed to trigger find command:', error);
        }
    };

    const boxId = String(item?.mac || '').replace(/[^a-fA-F0-9]/g, '').slice(-4).toUpperCase() || '0000';

    return (
        <article className={`tag-card ${isBuzzing ? 'tag-card-buzzing' : ''}`}>
            <div className="tag-card-row">
                <div className="tag-main-name">{medicineLabel(item)}</div>
                <div className="tag-chevron">v</div>
            </div>
            <div className="tag-card-meta">{String(item.mac || '').toLowerCase()}</div>
            <div className={`tag-status tag-status-${status.css}`}>{status.label}</div>
            <div className="tag-card-actions">
                <div className="tag-battery">Battery {formatBattery(item.battery)}</div>
                <button
                    type="button"
                    className={`tag-find-btn ${isBuzzing ? 'is-buzzing' : ''}`}
                    onClick={handleFind}
                    disabled={isBuzzing}
                >
                    Find tag
                </button>
            </div>
            {isBuzzing && <div className="tag-buzzing">Buzzing Box #{boxId}...</div>}
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

            const medData = medRes.ok ? await medRes.json() : [];
            const alertData = alertRes.ok ? await alertRes.json() : [];
            const statusData = statusRes.ok ? await statusRes.json() : { mqtt_connected: false };

            const map = (Array.isArray(positionData) ? positionData : []).reduce((acc, pos) => {
                if (pos?.mac) acc[pos.mac] = pos;
                return acc;
            }, {});

            // Merge status and position identities so dashboard still shows tags when only positions exist.
            const mergedByMac = {};
            (Array.isArray(medData) ? medData : []).forEach((item) => {
                if (item?.mac) mergedByMac[item.mac] = item;
            });
            (Array.isArray(positionData) ? positionData : []).forEach((pos) => {
                if (!pos?.mac) return;
                if (!mergedByMac[pos.mac]) {
                    mergedByMac[pos.mac] = {
                        mac: pos.mac,
                        medicine: pos.medicine,
                        battery: null,
                        temperature: null,
                        moving: false,
                        receiver_id: null,
                        time: pos.time,
                    };
                } else if (!mergedByMac[pos.mac].medicine && pos.medicine) {
                    mergedByMac[pos.mac].medicine = pos.medicine;
                }
            });

            setMedicines(Object.values(mergedByMac));
            setAlerts(Array.isArray(alertData) ? alertData : []);
            setStatus(statusData || { mqtt_connected: false });
            setPositionsByMac(map);
            setApiState((medRes.ok || Object.keys(map).length > 0) ? 'Online' : 'Error');
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
    const medicinesByMac = medicines.reduce((acc, item) => {
        if (item?.mac) acc[item.mac] = item;
        return acc;
    }, {});
    const mapTags = Object.values(positionsByMac)
        .filter((pos) => Number.isFinite(Number(pos?.x)) && Number.isFinite(Number(pos?.y)))
        .map((pos) => {
            const base = medicinesByMac[pos.mac] || {};
            return {
                ...base,
                ...pos,
                mac: pos.mac,
                medicine: base.medicine || pos.medicine,
            };
        });
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
                        <div className="map-view-container">
                            {/* Measurement Grid with Labels */}
                            <div className="map-grid-overlay">
                                { /* Vertical grid lines (X) - Using same mapping as dots */ }
                                {[...Array(11)].map((_, i) => (
                                    <div key={`v-${i}`} className="grid-line vertical" style={{ left: `${i * 9.2 + 4}%` }}>
                                        <span className="grid-label x-label">{i}</span>
                                    </div>
                                ))}
                                { /* Horizontal grid lines (Y) */ }
                                {[...Array(11)].map((_, i) => (
                                    <div key={`h-${i}`} className="grid-line horizontal" style={{ top: `${(10-i) * 9.2 + 4}%` }}>
                                        <span className="grid-label y-label">{i}</span>
                                    </div>
                                ))}
                            </div>

                            {/* Rooms positioned to match the 10x10 coordinate system */}
                            {/* Uses top/left logic to match markers: (x,y) -> left:x*10, top:(10-y)*10 */}
                            <div className="room-layer">
                                {/* Bottom Left Area (0-4, 0-4) mapped to 4-96 scale */}
                                <div className="map-room zone-nurse" style={{ left: '4%', top: '59.2%', width: '36.8%', height: '36.8%' }}>
                                    <span className="room-label">Nurse Station</span>
                                </div>
                                {/* Center Bottom (4.5-7, 0-4) */}
                                <div className="map-room zone-cold" style={{ left: '45.4%', top: '59.2%', width: '23%', height: '36.8%' }}>
                                    <span className="room-label">Cold Storage</span>
                                </div>
                                {/* Bottom Right (7.5-10, 0-4) */}
                                <div className="map-room zone-pharmacy" style={{ left: '73%', top: '59.2%', width: '23%', height: '36.8%' }}>
                                    <span className="room-label">Pharmacy</span>
                                </div>
                                {/* Top Right Area (6-10, 5-10) */}
                                <div className="map-room zone-icu" style={{ left: '59.2%', top: '4%', width: '36.8%', height: '46%' }}>
                                    <span className="room-label">ICU Ward</span>
                                </div>
                                {/* Middle Corridor (0-5.5, 4.5-5.5) */}
                                <div className="map-room zone-corridor" style={{ left: '4%', top: '45.4%', width: '50.6%', height: '9.2%' }}>
                                    <span className="room-label">Main Corridor</span>
                                </div>
                                {/* Top Left Area (0-5.5, 6-10) */}
                                <div className="map-room zone-storage" style={{ left: '4%', top: '4%', width: '50.6%', height: '36.8%' }}>
                                    <span className="room-label">Storage A</span>
                                </div>
                            </div>

                            {/* Tags Layer */}
                            <div className="marker-layer">
                                {mapTags.map((m, i) => {
                                    const coord = worldToMapPercent(m.x, m.y);
                                    const state = deriveStatus(m);

                                    // Count how many tags before this one have it the same (x,y)
                                    const stackIdx = mapTags.slice(0, i).filter(other => 
                                        Math.abs(other.x - m.x) < 0.1 && Math.abs(other.y - m.y) < 0.1
                                    ).length;

                                    return (
                                        <div
                                            key={m.mac || i}
                                            className="map-marker"
                                            style={{
                                                left: `${coord.x}%`,
                                                top: `${coord.y}%`,
                                                // Stack vertically downwards from the coordinate
                                                transform: `translateY(${stackIdx * 23}px)`,
                                                zIndex: 200 + stackIdx,
                                                opacity: 1,
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

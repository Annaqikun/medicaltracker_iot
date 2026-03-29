import { useEffect, useState } from 'react';

const REFRESH_INTERVAL_MS = 2000;
const FLIP_Y_AXIS = true;

function formatBattery(value) {
    if (value === null || value === undefined) return 'N/A';
    return `${Math.round(Number(value))}%`;
}

function formatTemp(value) {
    if (value === null || value === undefined) return 'N/A';
    return `${Number(value).toFixed(1)}\u00B0C`;
}

function formatDistance(value) {
    if (value === null || value === undefined) return 'N/A';
    return `${Number(value).toFixed(1)}m`;
}

function deriveStatus(item) {
    const battery = Number(item.battery);

    if (item.hasAlert) {
        const type = item.alertType || 'alert';
        const css = item.alertSeverity === 'critical' ? 'critical' : 'warning';
        return { label: type, css };
    }
    if (!Number.isNaN(battery) && battery <= 20) return { label: 'low battery', css: 'critical' };
    if (item.hasData) return { label: 'stable', css: 'stable' };
    return { label: 'registered', css: 'registered' };
}

function medicineLabel(item) {
    return item?.medicine_name || item?.medicine || `Tag ${String(item?.mac || 'Unknown').slice(-4)}`;
}

function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
}

function computeBounds(receivers, tags) {
    const allX = [];
    const allY = [];
    Object.values(receivers).forEach((r) => { allX.push(r.x); allY.push(r.y); });
    tags.forEach((t) => {
        if (Number.isFinite(Number(t.x))) allX.push(Number(t.x));
        if (Number.isFinite(Number(t.y))) allY.push(Number(t.y));
    });
    if (allX.length === 0) return { minX: 0, maxX: 10, minY: 0, maxY: 10 };
    const pad = 1;
    return {
        minX: Math.min(...allX) - pad,
        maxX: Math.max(...allX) + pad,
        minY: Math.min(...allY) - pad,
        maxY: Math.max(...allY) + pad,
    };
}

function worldToMapPercent(x, y, bounds) {
    const normalizedX = (Number(x) - bounds.minX) / (bounds.maxX - bounds.minX);
    const normalizedY = (Number(y) - bounds.minY) / (bounds.maxY - bounds.minY);
    const left = clamp(normalizedX * 92 + 4, 3, 97);
    const top = clamp((FLIP_Y_AXIS ? 1 - normalizedY : normalizedY) * 92 + 4, 3, 97);
    return { x: left, y: top };
}

async function safeFetch(url) {
    try {
        const res = await fetch(url);
        if (res.ok) return res.json();
    } catch (_) { /* degrade gracefully */ }
    return [];
}

const TagCard = ({ item }) => {
    const [isBuzzing, setIsBuzzing] = useState(false);
    const status = deriveStatus(item);

    const handleFind = async () => {
        if (!item?.mac || isBuzzing) return;

        setIsBuzzing(true);
        setTimeout(() => setIsBuzzing(false), 5000);

        try {
            await fetch(`/api/find/${item.mac}`, {
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

            <div className="tag-card-stats">
                <span>Bat {formatBattery(item.battery)}</span>
                <span>Temp {formatTemp(item.temperature)}</span>
                <span>Dist {formatDistance(item.distance)}</span>
                <span className={item.moving ? 'moving-yes' : 'moving-no'}>{item.moving ? 'Moving' : 'Still'}</span>
            </div>

            {item.confidence != null && (
                <div className="tag-card-stats">
                    <span>Confidence {Math.round(Number(item.confidence))}</span>
                    <span>Method {item.method || 'N/A'}</span>
                </div>
            )}

            <div className="tag-card-actions">
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

const HistoryPage = () => {
    const [tags, setTags] = useState([]);
    const [selectedMac, setSelectedMac] = useState('');
    const [hours, setHours] = useState(24);
    const [alertHistory, setAlertHistory] = useState([]);
    const [scanHistory, setScanHistory] = useState([]);
    const [loading, setLoading] = useState(false);
    const [dbAvailable, setDbAvailable] = useState(true);

    useEffect(() => {
        safeFetch('/api/tags').then((data) => {
            const t = Array.isArray(data) ? data : [];
            setTags(t);
            if (t.length > 0 && !selectedMac) setSelectedMac(t[0].mac);
        });
    }, []);

    const fetchHistory = async () => {
        setLoading(true);
        setDbAvailable(true);
        try {
            const [alerts, scans] = await Promise.all([
                fetch(`/api/history/alerts?hours=${hours}`),
                selectedMac ? fetch(`/api/history/scans/${encodeURIComponent(selectedMac)}?hours=${hours}`) : Promise.resolve(null),
            ]);
            if (alerts.status === 503) { setDbAvailable(false); setLoading(false); return; }
            setAlertHistory(alerts.ok ? await alerts.json() : []);
            setScanHistory(scans && scans.ok ? await scans.json() : []);
        } catch {
            setDbAvailable(false);
        }
        setLoading(false);
    };

    useEffect(() => { if (selectedMac || tags.length === 0) fetchHistory(); }, [selectedMac, hours]);

    if (!dbAvailable) {
        return (
            <div className="history-page">
                <section className="panel" style={{ gridColumn: '1 / -1' }}>
                    <div className="panel-head"><div><div className="panel-kicker">History</div><h2 className="panel-title">InfluxDB Unavailable</h2></div></div>
                    <div className="panel-body"><div className="empty-hint">InfluxDB is not connected. Historical data is not available.</div></div>
                </section>
            </div>
        );
    }

    return (
        <div className="history-page">
            <section className="panel history-controls-panel">
                <div className="panel-head">
                    <div>
                        <div className="panel-kicker">Filters</div>
                        <h2 className="panel-title">Query History</h2>
                    </div>
                </div>
                <div className="panel-body">
                    <div className="provision-form">
                        <div className="form-row">
                            <label className="form-label">Tag</label>
                            <select className="form-input" value={selectedMac} onChange={(e) => setSelectedMac(e.target.value)}>
                                {tags.map((t) => <option key={t.mac} value={t.mac}>{t.medicine_name} ({t.mac})</option>)}
                            </select>
                        </div>
                        <div className="form-row">
                            <label className="form-label">Time Range</label>
                            <select className="form-input" value={hours} onChange={(e) => setHours(Number(e.target.value))}>
                                <option value={1}>Last 1 hour</option>
                                <option value={6}>Last 6 hours</option>
                                <option value={24}>Last 24 hours</option>
                                <option value={72}>Last 3 days</option>
                                <option value={168}>Last 7 days</option>
                            </select>
                        </div>
                        <button className="provision-btn" onClick={fetchHistory} disabled={loading}>
                            {loading ? 'Loading...' : 'Refresh'}
                        </button>
                    </div>
                </div>
            </section>

            <section className="panel history-scans-panel">
                <div className="panel-head">
                    <div>
                        <div className="panel-kicker">Scan Log</div>
                        <h2 className="panel-title">Tag History</h2>
                    </div>
                    <div className="pill-gray">{scanHistory.length}</div>
                </div>
                <div className="panel-body">
                    {scanHistory.length === 0 ? (
                        <div className="empty-hint">No scan history for this tag in the selected range.</div>
                    ) : (
                        <div className="history-table-wrap">
                            <table className="provision-table">
                                <thead>
                                    <tr>
                                        <th>Time</th>
                                        <th>Type</th>
                                        <th>Receiver</th>
                                        <th>Dist</th>
                                        <th>Temp</th>
                                        <th>Bat</th>
                                        <th>Seq</th>
                                        <th>Moving</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {scanHistory.slice().reverse().map((s, i) => (
                                        <tr key={i}>
                                            <td className="mono">{s.time ? new Date(s.time).toLocaleString() : ''}</td>
                                            <td>{s.measurement === 'medicine_position' ? 'position' : 'scan'}</td>
                                            <td>{s.receiver_id || '-'}</td>
                                            <td>{s.distance != null ? Number(s.distance).toFixed(2) + 'm' : s.x != null ? `(${Number(s.x).toFixed(1)}, ${Number(s.y).toFixed(1)})` : '-'}</td>
                                            <td>{s.temperature != null ? Number(s.temperature).toFixed(1) + '\u00B0C' : '-'}</td>
                                            <td>{s.battery != null ? s.battery + '%' : '-'}</td>
                                            <td className="mono">{s.sequence_number ?? '-'}</td>
                                            <td>{s.moving != null ? (s.moving ? 'Yes' : 'No') : '-'}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            </section>

            <section className="panel history-alerts-panel">
                <div className="panel-head">
                    <div>
                        <div className="panel-kicker">Alert Log</div>
                        <h2 className="panel-title">Alert History</h2>
                    </div>
                    <div className="pill-gray">{alertHistory.length}</div>
                </div>
                <div className="panel-body">
                    {alertHistory.length === 0 ? (
                        <div className="empty-hint">No alerts in the selected range.</div>
                    ) : (
                        <div className="history-table-wrap">
                            <table className="provision-table">
                                <thead>
                                    <tr>
                                        <th>Time</th>
                                        <th>MAC</th>
                                        <th>Type</th>
                                        <th>Severity</th>
                                        <th>Message</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {alertHistory.map((a, i) => (
                                        <tr key={i} className={a.severity === 'critical' ? 'row-critical' : a.alert_type === 'resolved' ? 'row-resolved' : ''}>
                                            <td className="mono">{a.time ? new Date(a.time).toLocaleString() : ''}</td>
                                            <td className="mono">{a.mac}</td>
                                            <td>{a.alert_type}</td>
                                            <td><span className={`severity-badge sev-${a.severity}`}>{a.severity}</span></td>
                                            <td>{a.message}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            </section>
        </div>
    );
};

const ProvisionPage = () => {
    const [tags, setTags] = useState([]);
    const [mac, setMac] = useState('');
    const [medicineName, setMedicineName] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [message, setMessage] = useState(null);

    // USB serial provisioning state
    const [usbPorts, setUsbPorts] = useState([]);
    const [selectedPort, setSelectedPort] = useState('');
    const [usbMedicineName, setUsbMedicineName] = useState('');
    const [flashing, setFlashing] = useState(false);
    const [flashSteps, setFlashSteps] = useState([]);
    const [flashResult, setFlashResult] = useState(null);

    const fetchTags = async () => {
        const data = await safeFetch('/api/tags');
        setTags(Array.isArray(data) ? data : []);
    };

    const scanUsb = async () => {
        const data = await safeFetch('/api/provision/usb');
        const ports = data?.ports || [];
        setUsbPorts(ports);
        if (ports.length > 0 && !selectedPort) setSelectedPort(ports[0]);
    };

    useEffect(() => {
        fetchTags();
        scanUsb();
        const timer = setInterval(fetchTags, 5000);
        const usbTimer = setInterval(scanUsb, 3000);
        return () => { clearInterval(timer); clearInterval(usbTimer); };
    }, []);

    const handleFlash = async (e) => {
        e.preventDefault();
        if (!selectedPort || !usbMedicineName.trim()) return;
        setFlashing(true);
        setFlashSteps([]);
        setFlashResult(null);
        try {
            const params = new URLSearchParams({ port: selectedPort, medicine_name: usbMedicineName.trim() });
            const res = await fetch(`/api/provision/flash?${params}`, { method: 'POST' });
            const data = await res.json();
            if (res.ok) {
                setFlashSteps(data.steps || []);
                setFlashResult({ type: 'ok', text: `Provisioned ${data.mac} as "${data.medicine_name}"` });
                setUsbMedicineName('');
                fetchTags();
            } else {
                setFlashResult({ type: 'err', text: data.detail || 'Provisioning failed' });
            }
        } catch {
            setFlashResult({ type: 'err', text: 'Network error' });
        }
        setFlashing(false);
    };

    const handleRegister = async (e) => {
        e.preventDefault();
        if (!mac.trim() || !medicineName.trim()) return;
        setSubmitting(true);
        setMessage(null);
        try {
            const res = await fetch(`/api/tags?mac=${encodeURIComponent(mac.trim())}&medicine_name=${encodeURIComponent(medicineName.trim())}`, { method: 'POST' });
            if (res.ok) {
                const data = await res.json();
                setMessage({ type: 'ok', text: `Registered ${data.mac} — key: ${data.hmac_key_hex}` });
                setMac('');
                setMedicineName('');
                fetchTags();
            } else {
                const err = await res.json().catch(() => ({}));
                setMessage({ type: 'err', text: err.detail || 'Registration failed' });
            }
        } catch {
            setMessage({ type: 'err', text: 'Network error' });
        }
        setSubmitting(false);
    };

    const handleRemove = async (tagMac) => {
        if (!confirm(`Remove tag ${tagMac}?`)) return;
        try {
            const res = await fetch(`/api/tags/${encodeURIComponent(tagMac)}`, { method: 'DELETE' });
            if (res.ok) fetchTags();
        } catch { /* ignore */ }
    };

    return (
        <div className="provision-page">
            <div className="provision-forms">
                <section className="panel">
                    <div className="panel-head">
                        <div>
                            <div className="panel-kicker">USB Serial</div>
                            <h2 className="panel-title">Flash Tag via USB</h2>
                        </div>
                        <div className={usbPorts.length > 0 ? 'pill-green' : 'pill-gray'}>
                            {usbPorts.length > 0 ? `${usbPorts.length} device${usbPorts.length > 1 ? 's' : ''}` : 'No device'}
                        </div>
                    </div>
                    <div className="panel-body">
                        {usbPorts.length === 0 ? (
                            <div className="empty-hint">Plug in M5 tag via USB to begin provisioning.</div>
                        ) : (
                            <form className="provision-form" onSubmit={handleFlash}>
                                <div className="form-row">
                                    <label className="form-label">USB Port</label>
                                    <select className="form-input" value={selectedPort} onChange={(e) => setSelectedPort(e.target.value)}>
                                        {usbPorts.map((p) => <option key={p} value={p}>{p}</option>)}
                                    </select>
                                </div>
                                <div className="form-row">
                                    <label className="form-label">Medicine Name</label>
                                    <input className="form-input" type="text" placeholder="Insulin" value={usbMedicineName} onChange={(e) => setUsbMedicineName(e.target.value)} />
                                </div>
                                <button type="submit" className="provision-btn" disabled={flashing}>
                                    {flashing ? 'Flashing...' : 'Flash & Register'}
                                </button>
                            </form>
                        )}
                        {flashSteps.length > 0 && (
                            <div className="flash-steps">
                                {flashSteps.map((step, i) => (
                                    <div key={i} className="flash-step">{step}</div>
                                ))}
                            </div>
                        )}
                        {flashResult && (
                            <div className={`provision-msg ${flashResult.type === 'ok' ? 'msg-ok' : 'msg-err'}`}>
                                {flashResult.text}
                            </div>
                        )}
                    </div>
                </section>

                <section className="panel">
                    <div className="panel-head">
                        <div>
                            <div className="panel-kicker">Manual</div>
                            <h2 className="panel-title">Register Tag by MAC</h2>
                        </div>
                    </div>
                    <div className="panel-body">
                        <form className="provision-form" onSubmit={handleRegister}>
                            <div className="form-row">
                                <label className="form-label">MAC Address</label>
                                <input className="form-input" type="text" placeholder="4C:75:25:CB:86:62" value={mac} onChange={(e) => setMac(e.target.value)} />
                            </div>
                            <div className="form-row">
                                <label className="form-label">Medicine Name</label>
                                <input className="form-input" type="text" placeholder="Insulin" value={medicineName} onChange={(e) => setMedicineName(e.target.value)} />
                            </div>
                            <button type="submit" className="provision-btn" disabled={submitting}>
                                {submitting ? 'Registering...' : 'Register Tag'}
                            </button>
                        </form>
                        {message && (
                            <div className={`provision-msg ${message.type === 'ok' ? 'msg-ok' : 'msg-err'}`}>
                                {message.text}
                            </div>
                        )}
                    </div>
                </section>
            </div>

            <section className="panel provision-list-panel">
                <div className="panel-head">
                    <div>
                        <div className="panel-kicker">Registry</div>
                        <h2 className="panel-title">Registered Tags</h2>
                    </div>
                    <div className="pill-green">{tags.length}</div>
                </div>
                <div className="panel-body">
                    {tags.length === 0 ? (
                        <div className="empty-hint">No tags registered yet.</div>
                    ) : (
                        <table className="provision-table">
                            <thead>
                                <tr>
                                    <th>MAC</th>
                                    <th>Medicine</th>
                                    <th>Tag ID</th>
                                    <th>Registered</th>
                                    <th></th>
                                </tr>
                            </thead>
                            <tbody>
                                {tags.map((t) => (
                                    <tr key={t.mac}>
                                        <td className="mono">{t.mac}</td>
                                        <td>{t.medicine_name}</td>
                                        <td>{t.tag_id}</td>
                                        <td>{t.registered_at ? new Date(t.registered_at).toLocaleString() : 'N/A'}</td>
                                        <td>
                                            <button className="remove-btn" onClick={() => handleRemove(t.mac)}>Remove</button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                </div>
            </section>
        </div>
    );
};

function App() {
    const [page, setPage] = useState('dashboard');
    const [devices, setDevices] = useState([]);
    const [positionsByMac, setPositionsByMac] = useState({});
    const [alerts, setAlerts] = useState([]);
    const [status, setStatus] = useState({ mqtt_connected: false });
    const [receivers, setReceivers] = useState({});
    const [apiState, setApiState] = useState('Connecting');

    const fetchData = async () => {
        try {
            const [tagsData, medData, positionData, alertData, statusRes] = await Promise.all([
                safeFetch('/api/tags'),
                safeFetch('/api/medicines'),
                safeFetch('/api/positions'),
                safeFetch('/api/alerts'),
                fetch('/api/status'),
            ]);

            const statusData = statusRes.ok ? await statusRes.json() : { mqtt_connected: false };

            // Build device list: start from whitelist (tags), merge scan + position data
            const merged = {};

            // Layer 1: Registered tags (whitelist) — always show these
            (Array.isArray(tagsData) ? tagsData : []).forEach((tag) => {
                if (!tag?.mac) return;
                const mac = tag.mac.toUpperCase();
                merged[mac] = {
                    mac,
                    medicine_name: tag.medicine_name,
                    medicine: tag.medicine_name,
                    battery: null,
                    temperature: null,
                    distance: null,
                    moving: false,
                    hasData: false,
                };
            });

            // Layer 2: Scan data (latest status from receivers)
            (Array.isArray(medData) ? medData : []).forEach((item) => {
                if (!item?.mac) return;
                const mac = item.mac.toUpperCase();
                merged[mac] = {
                    ...merged[mac],
                    ...item,
                    mac,
                    medicine: merged[mac]?.medicine_name || item.medicine || merged[mac]?.medicine,
                    hasData: true,
                };
            });

            // Flag tags that have active alerts (keep latest alert per mac)
            const alertsByMac = {};
            (Array.isArray(alertData) ? alertData : []).forEach((a) => {
                if (!a?.mac || a.resolved) return;
                const mac = a.mac.toUpperCase();
                if (!alertsByMac[mac]) alertsByMac[mac] = a;
            });
            Object.values(merged).forEach((dev) => {
                const alert = alertsByMac[dev.mac];
                dev.hasAlert = !!alert;
                dev.alertType = alert?.alert_type || null;
                dev.alertMessage = alert?.message || null;
                dev.alertSeverity = alert?.severity || null;
            });

            // Layer 3: Position data (trilaterated positions)
            const posMap = {};
            (Array.isArray(positionData) ? positionData : []).forEach((pos) => {
                if (!pos?.mac) return;
                const mac = pos.mac.toUpperCase();
                posMap[mac] = pos;
                if (merged[mac]) {
                    merged[mac].confidence = pos.confidence;
                    merged[mac].method = pos.method;
                    if (!merged[mac].medicine && pos.medicine) {
                        merged[mac].medicine = pos.medicine;
                    }
                }
            });

            setDevices(Object.values(merged));
            setPositionsByMac(posMap);
            setAlerts(Array.isArray(alertData) ? alertData : []);
            setStatus(statusData || { mqtt_connected: false });
            setReceivers(statusData?.receivers || {});
            setApiState(Object.keys(merged).length > 0 ? 'Online' : 'Error');
        } catch (error) {
            setApiState('Error');
            console.error(error);
        }
    };

    useEffect(() => {
        fetchData();
        const timer = setInterval(fetchData, REFRESH_INTERVAL_MS);
        return () => clearInterval(timer);
    }, []);

    const devicesByMac = devices.reduce((acc, item) => {
        if (item?.mac) acc[item.mac] = item;
        return acc;
    }, {});
    const mapTags = Object.values(positionsByMac)
        .filter((pos) => Number.isFinite(Number(pos?.x)) && Number.isFinite(Number(pos?.y)))
        .map((pos) => {
            const mac = pos.mac?.toUpperCase();
            const base = devicesByMac[mac] || {};
            return {
                ...base,
                ...pos,
                mac,
                medicine: base.medicine_name || base.medicine || pos.medicine,
            };
        });
    const positionedMacs = new Set(mapTags.map((item) => item.mac));
    const fallbackMapTags = devices
        .filter((item) =>
            item?.mac &&
            item.hasData &&
            !positionedMacs.has(item.mac) &&
            item.receiver_id &&
            receivers[item.receiver_id]
        )
        .map((item) => {
            const receiverPos = receivers[item.receiver_id];
            return {
                ...item,
                x: receiverPos.x,
                y: receiverPos.y,
                method: item.method || 'receiver_fallback',
                confidence: item.confidence ?? null,
                isFallback: true,
            };
        });
    const visibleMapTags = [...mapTags, ...fallbackMapTags];
    const mapBounds = computeBounds(receivers, visibleMapTags);
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
                        <div className="stat-label">Tags</div>
                        <div className="stat-value neutral">{devices.length}</div>
                    </div>
                </div>

                <nav className="topbar-nav">
                    <button className={`nav-tab ${page === 'dashboard' ? 'active' : ''}`} onClick={() => setPage('dashboard')}>Dashboard</button>
                    <button className={`nav-tab ${page === 'provision' ? 'active' : ''}`} onClick={() => setPage('provision')}>Provision</button>
                    <button className={`nav-tab ${page === 'history' ? 'active' : ''}`} onClick={() => setPage('history')}>History</button>
                </nav>
            </header>

            {page === 'provision' ? <ProvisionPage /> : page === 'history' ? <HistoryPage /> : (
            <main className="layout">
                <section className="panel inventory">
                    <div className="panel-head">
                        <div>
                            <div className="panel-kicker">Inventory</div>
                            <h2 className="panel-title">Medicine Tags</h2>
                        </div>
                        <div className="pill-green">{devices.filter(d => d.hasData).length} active</div>
                    </div>

                    <div className="panel-body tags-list">
                        {devices.length === 0 && <div className="empty-hint">No tags registered.</div>}
                        {devices.map((item, idx) => (
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
                            <div className="map-grid-overlay">
                                {[...Array(6)].map((_, i) => {
                                    const pct = i / 5;
                                    const val = mapBounds.minX + pct * (mapBounds.maxX - mapBounds.minX);
                                    return (
                                        <div key={`v-${i}`} className="grid-line vertical" style={{ left: `${pct * 92 + 4}%` }}>
                                            <span className="grid-label x-label">{val.toFixed(1)}</span>
                                        </div>
                                    );
                                })}
                                {[...Array(6)].map((_, i) => {
                                    const pct = i / 5;
                                    const val = mapBounds.minY + pct * (mapBounds.maxY - mapBounds.minY);
                                    return (
                                        <div key={`h-${i}`} className="grid-line horizontal" style={{ top: `${(1 - pct) * 92 + 4}%` }}>
                                            <span className="grid-label y-label">{val.toFixed(1)}</span>
                                        </div>
                                    );
                                })}
                            </div>

                            <div className="receiver-layer">
                                {Object.entries(receivers).map(([id, pos]) => {
                                    const coord = worldToMapPercent(pos.x, pos.y, mapBounds);
                                    return (
                                        <div
                                            key={id}
                                            className="receiver-marker"
                                            style={{ left: `${coord.x}%`, top: `${coord.y}%` }}
                                        >
                                            <span className="receiver-icon">&#x25B2;</span>
                                            <span className="receiver-label">{id.replace('_', ' ')}</span>
                                        </div>
                                    );
                                })}
                            </div>

                            <div className="marker-layer">
                                {visibleMapTags.map((m, i) => {
                                    const coord = worldToMapPercent(m.x, m.y, mapBounds);
                                    const state = deriveStatus(m);
                                    const stackIdx = visibleMapTags.slice(0, i).filter(other =>
                                        Math.abs(other.x - m.x) < 0.1 && Math.abs(other.y - m.y) < 0.1
                                    ).length;

                                    return (
                                        <div
                                            key={m.mac || i}
                                            className="map-marker"
                                            style={{
                                                left: `${coord.x}%`,
                                                top: `${coord.y}%`,
                                                transform: `translateY(${stackIdx * 23}px)`,
                                                zIndex: 200 + stackIdx,
                                                opacity: m.isFallback ? 0.72 : 1,
                                            }}
                                            title={m.isFallback ? `Approximate: last seen by ${m.receiver_id}` : undefined}
                                        >
                                            <span className={`dot dot-${state.css}`} />
                                            <span className="marker-label">
                                                {medicineLabel(m)}
                                                {m.isFallback ? ' (approx)' : ''}
                                            </span>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    </div>

                    <div className="legend-row">
                        <div className="legend-item"><span className="legend-dot lg-stable" />Stable</div>
                        <div className="legend-item"><span className="legend-dot lg-moving" />Moving</div>
                        <div className="legend-item"><span className="legend-dot lg-warning" />Alert</div>
                        <div className="legend-item"><span className="legend-tri" />RPi Receiver</div>
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
                            alerts.slice(0, 20).map((a, idx) => (
                                <article key={`${a.mac || 'alert'}-${idx}`} className={`alert-item ${a.resolved ? 'alert-resolved' : ''} ${a.severity === 'critical' ? 'alert-critical' : ''}`}>
                                    <div className="alert-title-line">
                                        {a.alert_type || 'alert'}
                                        {a.resolved && <span className="alert-resolved-badge">resolved</span>}
                                    </div>
                                    <div className="alert-copy">{a.message || 'No details.'}</div>
                                    <div className="alert-meta">{a.mac} — {a.time ? new Date(a.time).toLocaleTimeString() : ''}</div>
                                </article>
                            ))
                        )}
                    </div>
                </section>
            </main>
            )}
        </div>
    );
}

export default App;

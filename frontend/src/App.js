import React, { useEffect, useState } from 'react';
import './App.css';

const App = () => {
  const [tags, setTags] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsHost = process.env.REACT_APP_WS_HOST || window.location.hostname;
    const wsPort = process.env.REACT_APP_WS_PORT || '3002';  
    const wsUrl = `${wsProtocol}//${wsHost}:${wsPort}`;
    
    console.log('✅ Connecting to WebSocket:', wsUrl);
    const socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      console.log('✅ WebSocket connected successfully');
      setConnected(true);
      setError(null);
    };

    socket.onmessage = (event) => {
      console.log('📨 Received message:', event.data);
      const data = JSON.parse(event.data);
      
      // Handle location updates
      if (data.type === 'location') {
        console.log('📍 Location update for:', data.name);
        setTags((prevTags) => {
          const existingIndex = prevTags.findIndex(tag => tag.mac === data.mac);
          const updatedTag = {
            mac: data.mac,
            name: data.name || `Tag ${data.mac.slice(-4)}`,
            x: data.x,
            y: data.y,
            temperature: data.temperature,
            battery: data.battery,
            zone: data.zone,
            status: data.status || 'normal',
            lastSeen: new Date(),
          };
          
          if (existingIndex >= 0) {
            const newTags = [...prevTags];
            newTags[existingIndex] = updatedTag;
            return newTags;
          }
          return [...prevTags, updatedTag];
        });
      } 
      // Handle alerts
      else if (data.type === 'alert') {
        console.log('🚨 Alert received:', data.message);
        setAlerts((prevAlerts) => [
          {
            id: data.id || Date.now(),
            type: data.alertType || data.type,
            message: data.message,
            timestamp: new Date(data.timestamp || Date.now()),
            mac: data.mac,
          },
          ...prevAlerts.slice(0, 19),
        ]);
      }
    };

    socket.onerror = (error) => {
      console.error('❌ WebSocket error:', error);
      setConnected(false);
      setError('Failed to connect to server');
    };

    socket.onclose = (event) => {
      console.log('🔴 WebSocket closed:', event.code, event.reason);
      setConnected(false);
      if (!event.wasClean) {
        setError('Connection lost');
      }
    };

    return () => {
      socket.close();
    };
  }, []);

  return (
    <div className="dashboard">
      {/* Header */}
      <header className="dashboard-header">
        <h1>🏥 Hospital Medicine Tracking Dashboard</h1>
        <div className="header-stats">
          <span className="stat">📦 {tags.length} Tags</span>
          <span className="stat">⚠️ {alerts.length} Alerts</span>
          <span className={`stat connection-status ${connected ? 'connected' : 'disconnected'}`}>
            {connected ? '🟢 Connected' : '🔴 Disconnected'}
          </span>
        </div>
      </header>

      {/* Error Banner */}
      {error && (
        <div className="error-banner">
          ⚠️ {error} - Make sure backend server is running on port 3002
        </div>
      )}

      {/* Main Content */}
      <div className="dashboard-content">
        {/* Left Panel: Tag List */}
        <aside className="left-panel">
          <h2>Medicine Tags</h2>
          <div className="tag-list">
            {tags.length === 0 ? (
              <div className="empty-state">
                <p>No tags detected</p>
                <small>
                  {connected 
                    ? 'Waiting for MQTT data... Run test-publisher-spec.js' 
                    : 'Backend not connected - check if server.js is running'}
                </small>
              </div>
            ) : (
              tags.map((tag) => (
                <div key={tag.mac} className="tag-item">
                  <div className="tag-info">
                    <strong>{tag.name}</strong>
                    <span className="tag-mac">{tag.mac}</span>
                  </div>
                  <div className="tag-details">
                    <span className="tag-status" data-status={tag.status}>
                      {tag.status}
                    </span>
                    <span>🔋 {tag.battery}%</span>
                    <span>🌡️ {tag.temperature?.toFixed(1)}°C</span>
                  </div>
                  {tag.zone && <div className="tag-zone">📍 {tag.zone}</div>}
                </div>
              ))
            )}
          </div>
        </aside>

        {/* Center: Floor Map */}
        <main className="center-panel">
          <div className="floor-map">
            <h2>Floor Map</h2>
            <div className="map-container">
              <div className="map-placeholder">
                <p>📍 Floor plan will be displayed here</p>
                <small>Upload a floor plan image to see tag locations</small>
                {tags.length > 0 && (
                  <div className="tag-count-notice">
                    {tags.length} tag{tags.length !== 1 ? 's' : ''} being tracked
                  </div>
                )}
              </div>
            </div>
          </div>
        </main>

        {/* Right Panel: Alerts */}
        <aside className="right-panel">
          <h2>Alert Feed</h2>
          <div className="alert-list">
            {alerts.length === 0 ? (
              <p className="empty-state">No alerts</p>
            ) : (
              alerts.map((alert) => (
                <div key={alert.id} className="alert-item" data-alert-type={alert.type}>
                  <div className="alert-header">
                    <span className="alert-icon">
                      {alert.type === 'temperature' ? '🌡️' : 
                       alert.type === 'battery' ? '🔋' : 
                       alert.type === 'ble-lost' || alert.type === 'connection' ? '📡' : '⚠️'}
                    </span>
                    <span className="alert-time">
                      {alert.timestamp.toLocaleTimeString()}
                    </span>
                  </div>
                  <p className="alert-message">{alert.message}</p>
                </div>
              ))
            )}
          </div>
        </aside>
      </div>
    </div>
  );
};

export default App;
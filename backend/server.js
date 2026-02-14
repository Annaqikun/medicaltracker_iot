const express = require('express');
const mqtt = require('mqtt');
const WebSocket = require('ws');
const cors = require('cors');
const db = require('./database');

const app = express();
const port = 3001;

// Enable CORS
app.use(cors());
app.use(express.json());

// Connect to MQTT broker
//const mqttClient = mqtt.connect('mqtt://192.168.50.162:1883');

const mqttBroker = process.env.MQTT_BROKER || '192.168.50.162';
const mqttPort = process.env.MQTT_PORT || 1883;
const mqttUrl = `mqtt://${mqttBroker}:${mqttPort}`;

console.log(`Connecting to MQTT broker at ${mqttUrl}`);
const mqttClient = mqtt.connect(mqttUrl);

// MQTT Topics
const rssiTopic = 'hospital/rssi/#';              // RSSI data from RPi receivers
const locationTopic = 'hospital/location/#';      // Calculated locations
const alertsTopic = 'hospital/alerts/#';          // Alerts
const commandTopic = 'hospital/command/#';        // Commands to tags

mqttClient.on('connect', () => {
  console.log('Connected to MQTT Broker');
  mqttClient.subscribe([rssiTopic, locationTopic, alertsTopic], (err) => {
    if (!err) {
      console.log('Subscribed to topics:', { rssiTopic, locationTopic, alertsTopic });
    }
  });
});

// Store RSSI readings for trilateration
const rssiReadings = new Map(); // Key: medicine_mac, Value: array of readings

// Handle MQTT messages
mqttClient.on('message', (topic, message) => {
  try {
    const payload = JSON.parse(message.toString());
    console.log(`[${topic}]`, payload);
    
    // 1. Handle RSSI Data from RPi receivers
    if (topic.startsWith('hospital/rssi/')) {
      handleRSSIData(payload);
    }
    
    // 2. Handle calculated location updates
    else if (topic.startsWith('hospital/location/')) {
      handleLocationUpdate(payload);
    }
    
    // 3. Handle alerts
    else if (topic.startsWith('hospital/alerts/')) {
      handleAlert(payload);
    }
    
  } catch (error) {
    console.error('Error processing MQTT message:', error, message.toString());
  }
});

// Handle RSSI data from RPi4 receivers
function handleRSSIData(payload) {
  const { medicine_mac, receiver_id, rssi, temperature, battery, status_flags, timestamp } = payload;
  
  // Store RSSI reading
  if (!rssiReadings.has(medicine_mac)) {
    rssiReadings.set(medicine_mac, []);
  }
  
  const readings = rssiReadings.get(medicine_mac);
  readings.push({
    receiver_id,
    rssi,
    timestamp,
  });
  
  // Keep only last 10 readings per tag
  if (readings.length > 10) {
    readings.shift();
  }
  
  // Check for alerts based on status flags
  if (status_flags) {
    if (status_flags.temp_alert) {
      const tag = db.getTag(medicine_mac);
      db.addAlert({
        type: 'temperature',
        alertType: 'temperature',
        mac: medicine_mac,
        message: `${tag?.name || medicine_mac}: Temperature alert (${temperature}°C)`,
      });
      broadcastAlert({
        type: 'alert',
        alertType: 'temperature',
        mac: medicine_mac,
        message: `Temperature alert: ${temperature}°C`,
        timestamp: new Date().toISOString(),
      });
    }
    
    if (battery < 20) {
      const tag = db.getTag(medicine_mac);
      db.addAlert({
        type: 'battery',
        alertType: 'battery',
        mac: medicine_mac,
        message: `${tag?.name || medicine_mac}: Low battery (${battery}%)`,
      });
    }
  }
  
  // Simple trilateration could be done here if you have 3+ receivers
  // For now, we'll wait for the location update from your positioning engine
}

// Handle location update (after trilateration/positioning calculation)
function handleLocationUpdate(payload) {
  const { 
    medicine_mac, 
    medicine_name, 
    location, 
    temperature, 
    battery,
    calculated_from,
    timestamp 
  } = payload;
  
  // Determine status based on flags and battery
  let status = 'normal';
  if (battery < 20) status = 'alert';
  else if (battery < 40) status = 'warning';
  
  // Update tag in database
  const tag = db.upsertTag({
    mac: medicine_mac,
    name: medicine_name,
    x: location.x,
    y: location.y,
    zone: location.zone,
    accuracy: location.accuracy_meters,
    temperature: temperature,
    battery: battery,
    status: status,
    calculatedFrom: calculated_from,
    timestamp: timestamp,
  });
  
  // Broadcast to all WebSocket clients
  broadcastToClients({
    type: 'location',
    ...tag,
  });
}

// Handle alerts
function handleAlert(payload) {
  const alert = db.addAlert({
    type: payload.alert_type || payload.type,
    alertType: payload.alert_type || payload.type,
    mac: payload.medicine_mac,
    message: payload.message,
    severity: payload.severity || 'medium',
  });
  
  broadcastAlert({
    type: 'alert',
    ...alert,
  });
}

// Broadcast to all WebSocket clients
function broadcastToClients(data) {
  wss.clients.forEach(client => {
    if (client.readyState === WebSocket.OPEN) {
      client.send(JSON.stringify(data));
    }
  });
}

function broadcastAlert(alert) {
  wss.clients.forEach(client => {
    if (client.readyState === WebSocket.OPEN) {
      client.send(JSON.stringify(alert));
    }
  });
}

// WebSocket server
const wss = new WebSocket.Server({ port: 3002 });

wss.on('connection', (ws) => {
  console.log('WebSocket client connected');
  
  // Send all existing tags to new client
  const allTags = db.getAllTags();
  allTags.forEach(tag => {
    ws.send(JSON.stringify({ ...tag, type: 'location' }));
  });
  
  // Send recent alerts
  const recentAlerts = db.getRecentAlerts();
  recentAlerts.forEach(alert => {
    ws.send(JSON.stringify({ ...alert, type: 'alert' }));
  });

  ws.on('message', (message) => {
    try {
      const data = JSON.parse(message);
      
      // Handle client commands
      if (data.action === 'acknowledgeAlert') {
        db.acknowledgeAlert(data.alertId);
      } else if (data.action === 'findTag') {
        // Trigger find command via MQTT
        sendFindCommand(data.mac);
      }
    } catch (error) {
      console.error('Error processing WebSocket message:', error);
    }
  });

  ws.on('close', () => {
    console.log('WebSocket client disconnected');
  });
});

// REST API Endpoints

// Get all tags
app.get('/api/tags', (req, res) => {
  res.json(db.getAllTags());
});

// Get single tag
app.get('/api/tags/:mac', (req, res) => {
  const tag = db.getTag(req.params.mac);
  if (tag) {
    res.json(tag);
  } else {
    res.status(404).json({ error: 'Tag not found' });
  }
});

// Get tag location history
app.get('/api/tags/:mac/history', (req, res) => {
  const tag = db.getTag(req.params.mac);
  if (tag && tag.history) {
    res.json(tag.history);
  } else {
    res.status(404).json({ error: 'No history found' });
  }
});

// Get recent alerts
app.get('/api/alerts', (req, res) => {
  const limit = parseInt(req.query.limit) || 20;
  res.json(db.getRecentAlerts(limit));
});

// Acknowledge alert
app.post('/api/alerts/:id/acknowledge', (req, res) => {
  const alert = db.acknowledgeAlert(parseInt(req.params.id));
  if (alert) {
    // Broadcast acknowledgment to all clients
    broadcastToClients({
      type: 'alertAcknowledged',
      alertId: parseInt(req.params.id),
    });
    res.json(alert);
  } else {
    res.status(404).json({ error: 'Alert not found' });
  }
});

// Send "Find My Tag" command
app.post('/api/tags/:mac/find', (req, res) => {
  sendFindCommand(req.params.mac);
  res.json({ success: true, message: `Find command sent to ${req.params.mac}` });
});

// Helper function to send find command via MQTT
function sendFindCommand(mac) {
  const topic = `hospital/command/${mac}/find`;
  const payload = {
    timestamp: new Date().toISOString(),
    command: 'find',
    duration_seconds: 5,
    buzzer: true,
    vibration: true,
  };
  
  mqttClient.publish(topic, JSON.stringify(payload));
  console.log(`Find command sent to ${mac}`);
  
  // Notify all connected clients
  broadcastToClients({
    type: 'commandSent',
    command: 'find',
    mac: mac,
    timestamp: payload.timestamp,
  });
}

// Check for stale tags every 30 seconds
setInterval(() => {
  db.checkStaleTags();
}, 30000);

// Start server
app.listen(port, () => {
  console.log(`Backend server running on http://localhost:${port}`);
  console.log(`WebSocket server running on ws://localhost:3002`);
  console.log(`Database loaded with ${db.getAllTags().length} tags`);
});
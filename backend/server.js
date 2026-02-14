const express = require('express');
const mqtt = require('mqtt');
const WebSocket = require('ws');
const cors = require('cors');
const app = express();
const port = 3001;

// Enable CORS to allow requests from the frontend
app.use(cors());

// Connect to the MQTT broker
const mqttClient = mqtt.connect('mqtt://192.168.50.162:1883'); // Connect to Mosquitto broker

// MQTT Topics to Subscribe to
const locationTopic = 'hospital/medicine/location/#';
const alertsTopic = 'hospital/alerts/#';

mqttClient.on('connect', () => {
  console.log('Connected to MQTT Broker');
  mqttClient.subscribe([locationTopic, alertsTopic], (err) => {
    if (!err) {
      console.log(`Subscribed to topics: ${locationTopic}, ${alertsTopic}`);
    }
  });
});

// WebSocket server for real-time communication
const wss = new WebSocket.Server({ port: 3002 });

wss.on('connection', (ws) => {
  console.log('WebSocket client connected');
  // Send MQTT messages to WebSocket clients
  mqttClient.on('message', (topic, message) => {
    const data = { topic, message: message.toString() };
    ws.send(JSON.stringify(data)); // Send to WebSocket client
  });

  ws.on('close', () => {
    console.log('WebSocket client disconnected');
  });
});

// REST API: GET all tags (for now, returning dummy data)
app.get('/api/tags', (req, res) => {
  res.json([
    { id: 1, name: 'Tag 1', status: 'active' },
    { id: 2, name: 'Tag 2', status: 'inactive' },
  ]);
});

// REST API: GET single tag by MAC address
app.get('/api/tags/:mac', (req, res) => {
  const { mac } = req.params;
  res.json({ id: mac, name: `Tag ${mac}`, status: 'active' });
});

// Start the server
app.listen(port, () => {
  console.log(`Server running on http://localhost:${port}`);
});

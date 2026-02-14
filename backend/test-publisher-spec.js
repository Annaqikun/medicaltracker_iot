const mqtt = require('mqtt');

// Connect to MQTT broker
//const client = mqtt.connect('mqtt://192.168.50.162:1883');
const mqttBroker = process.env.MQTT_BROKER || '192.168.50.162';
const mqttPort = process.env.MQTT_PORT || 1883;
const mqttUrl = `mqtt://${mqttBroker}:${mqttPort}`;

console.log(`Connecting to MQTT broker at ${mqttUrl}`);
const client = mqtt.connect(mqttUrl);

// Mock RPi4 receivers
const receivers = [
  { id: 'rpi4_zone_a', x: 0, y: 0 },
  { id: 'rpi4_zone_b', x: 20, y: 0 },
  { id: 'rpi4_zone_c', x: 10, y: 15 },
];

// Mock medicine tags
const medicineTags = [
  { mac: 'A4:CF:12:34:56:78', name: 'Paracetamol', zone: 'Ward_A' },
  { mac: 'A4:CF:12:34:56:79', name: 'Aspirin', zone: 'Ward_B' },
  { mac: 'A4:CF:12:34:56:80', name: 'Insulin', zone: 'Storage' },
];

let sequenceNumber = 1000;

client.on('connect', () => {
  console.log('Connected to MQTT broker');
  console.log('Publishing test messages according to spec...\n');

  // Simulate RSSI data from multiple receivers
  setInterval(() => {
    medicineTags.forEach((tag) => {
      receivers.forEach((receiver) => {
        // Simulate RSSI reading (closer = stronger signal)
        const distance = Math.random() * 20;
        const rssi = -30 - distance * 3; // Rough RSSI calculation
        
        const rssiPayload = {
          timestamp: new Date().toISOString(),
          receiver_id: receiver.id,
          medicine_mac: tag.mac,
          rssi: Math.round(rssi),
          temperature: 23.5 + (Math.random() * 2 - 1),
          battery: Math.max(10, 85 - Math.floor(Math.random() * 10)),
          sequence_number: sequenceNumber++,
          status_flags: {
            moving: Math.random() > 0.8,
            temp_alert: Math.random() > 0.95,
            wifi_failover: false,
          },
        };

        const topic = `hospital/rssi/${receiver.id}`;
        client.publish(topic, JSON.stringify(rssiPayload));
      });
    });
    
    console.log(`Published RSSI data from ${receivers.length} receivers`);
  }, 3000);

  // Simulate calculated location updates (after trilateration)
  setInterval(() => {
    medicineTags.forEach((tag) => {
      const locationPayload = {
        timestamp: new Date().toISOString(),
        medicine_mac: tag.mac,
        medicine_name: tag.name,
        location: {
          x: Math.random() * 20,
          y: Math.random() * 15,
          zone: tag.zone,
          accuracy_meters: 1.5 + Math.random(),
        },
        calculated_from: receivers.map(r => r.id),
        temperature: 23.5 + (Math.random() * 2 - 1),
        battery: Math.max(10, 85 - Math.floor(Math.random() * 10)),
      };

      const topic = `hospital/location/${tag.mac}`;
      client.publish(topic, JSON.stringify(locationPayload));
      console.log(`📍 Location update: ${tag.name} at (${locationPayload.location.x.toFixed(1)}, ${locationPayload.location.y.toFixed(1)})`);
    });
  }, 5000);

  // Simulate random alerts
  setInterval(() => {
    if (Math.random() > 0.7) {
      const randomTag = medicineTags[Math.floor(Math.random() * medicineTags.length)];
      const alertTypes = ['temperature', 'battery', 'movement'];
      const alertType = alertTypes[Math.floor(Math.random() * alertTypes.length)];

      const alertPayload = {
        timestamp: new Date().toISOString(),
        alert_type: alertType,
        medicine_mac: randomTag.mac,
        message: `${randomTag.name}: ${alertType} threshold exceeded`,
        severity: 'high',
      };

      client.publish(`hospital/alerts/${randomTag.mac}`, JSON.stringify(alertPayload));
      console.log(`🚨 Alert: ${alertPayload.message}`);
    }
  }, 10000);
});

// Listen for find commands
client.subscribe('hospital/command/+/find', (err) => {
  if (!err) {
    console.log('Subscribed to find commands\n');
  }
});

client.on('message', (topic, message) => {
  if (topic.includes('/find')) {
    const command = JSON.parse(message.toString());
    console.log(`🔊 Find command received:`, command);
  }
});

console.log('Starting MQTT test publisher (matching spec)...');
console.log('Press Ctrl+C to stop\n');
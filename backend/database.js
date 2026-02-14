const fs = require('fs');
const path = require('path');

const DB_FILE = path.join(__dirname, 'tags-database.json');

class TagDatabase {
  constructor() {
    this.tags = new Map();
    this.alerts = [];
    this.loadFromFile();
  }

  // Load existing data from file
  loadFromFile() {
    try {
      if (fs.existsSync(DB_FILE)) {
        const data = JSON.parse(fs.readFileSync(DB_FILE, 'utf8'));
        data.tags.forEach(tag => this.tags.set(tag.mac, tag));
        this.alerts = data.alerts || [];
        console.log(`Loaded ${this.tags.size} tags from database`);
      }
    } catch (error) {
      console.error('Error loading database:', error);
    }
  }

  // Save to file
  saveToFile() {
    try {
      const data = {
        tags: Array.from(this.tags.values()),
        alerts: this.alerts.slice(-100), // Keep last 100 alerts
        lastUpdated: new Date().toISOString(),
      };
      fs.writeFileSync(DB_FILE, JSON.stringify(data, null, 2));
    } catch (error) {
      console.error('Error saving database:', error);
    }
  }

  // Update or add a tag
  upsertTag(tagData) {
    const existing = this.tags.get(tagData.mac);
    
    const tag = {
      mac: tagData.mac,
      name: tagData.name || (existing ? existing.name : `Tag ${tagData.mac.slice(-4)}`),
      x: tagData.x,
      y: tagData.y,
      temperature: tagData.temperature,
      battery: tagData.battery,
      zone: tagData.zone,
      status: tagData.status || 'normal',
      lastSeen: new Date().toISOString(),
      firstSeen: existing ? existing.firstSeen : new Date().toISOString(),
      history: existing ? existing.history : [],
    };

    // Keep location history (last 50 positions)
    if (existing) {
      tag.history = [
        ...existing.history.slice(-49),
        { x: tagData.x, y: tagData.y, timestamp: tag.lastSeen }
      ];
    }

    this.tags.set(tag.mac, tag);
    this.saveToFile();
    return tag;
  }

  // Add alert
  addAlert(alertData) {
    const alert = {
      id: Date.now(),
      type: alertData.alertType || alertData.type,
      message: alertData.message,
      mac: alertData.mac,
      timestamp: new Date().toISOString(),
      acknowledged: false,
    };
    
    this.alerts.unshift(alert); // Add to beginning
    this.alerts = this.alerts.slice(0, 100); // Keep last 100
    this.saveToFile();
    return alert;
  }

  // Get all tags
  getAllTags() {
    return Array.from(this.tags.values());
  }

  // Get tag by MAC
  getTag(mac) {
    return this.tags.get(mac);
  }

  // Get recent alerts
  getRecentAlerts(limit = 20) {
    return this.alerts.slice(0, limit);
  }

  // Acknowledge alert
  acknowledgeAlert(alertId) {
    const alert = this.alerts.find(a => a.id === alertId);
    if (alert) {
      alert.acknowledged = true;
      alert.acknowledgedAt = new Date().toISOString();
      this.saveToFile();
    }
    return alert;
  }

  // Check for stale tags (not seen in 2 minutes)
  checkStaleTags() {
    const now = Date.now();
    const staleThreshold = 2 * 60 * 1000; // 2 minutes

    this.tags.forEach(tag => {
      const lastSeenTime = new Date(tag.lastSeen).getTime();
      if (now - lastSeenTime > staleThreshold && tag.status !== 'offline') {
        tag.status = 'offline';
        this.addAlert({
          type: 'connection',
          alertType: 'ble-lost',
          message: `${tag.name}: Lost connection`,
          mac: tag.mac,
        });
      }
    });
    this.saveToFile();
  }
}

module.exports = new TagDatabase();
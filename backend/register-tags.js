const db = require('./database');

// Register your medicine tags
const medicineTags = [
  {
    mac: 'AA:BB:CC:DD:EE:01',
    name: 'Aspirin Box #1',
    zone: 'Ward A',
    x: 0,
    y: 0,
    temperature: 22,
    battery: 100,
    status: 'offline',
  },
  {
    mac: 'AA:BB:CC:DD:EE:02',
    name: 'Insulin Pack #2',
    zone: 'Storage Room',
    x: 0,
    y: 0,
    temperature: 22,
    battery: 100,
    status: 'offline',
  },
  {
    mac: 'AA:BB:CC:DD:EE:03',
    name: 'Antibiotics #3',
    zone: 'Pharmacy',
    x: 0,
    y: 0,
    temperature: 22,
    battery: 100,
    status: 'offline',
  },
];

console.log('Registering medicine tags...\n');

medicineTags.forEach(tag => {
  db.upsertTag(tag);
  console.log(`✓ Registered: ${tag.name} (${tag.mac})`);
});

console.log(`\n✅ Registered ${medicineTags.length} tags successfully!`);
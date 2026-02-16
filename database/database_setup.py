import sqlite3

with sqlite3.connect("hospital_iot.db") as conn:
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON;")
    
    try:
        print("\nCreating Table #1 (Medicine Tags)")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS medicine_tags(
                tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
                mac_address TEXT UNIQUE NOT NULL,
                medicine_name TEXT NOT NULL,
                medicine_type TEXT NOT NULL,
                registered_at TEXT DEFAULT (datetime('now'))
            )
        """)
        print("Table #1 Created Successfully.")
        
        print("\nCreating Table #2 (Receivers)")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS receivers(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                receiver_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                x_position REAL NOT NULL,
                y_position REAL NOT NULL,
                floor_level INTEGER DEFAULT 1
            )
        """)
        print("Table #2 Created Successfully.")
        
        print("\nCreating Table #3 (RSSI Readings)")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rssi_readings(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag_id INTEGER NOT NULL,
                receiver_id TEXT NOT NULL,
                rssi INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                sequence_number INTEGER NOT NULL,
                FOREIGN KEY (tag_id) REFERENCES medicine_tags(tag_id),
                FOREIGN KEY (receiver_id) REFERENCES receivers(receiver_id),
                UNIQUE(tag_id, receiver_id, sequence_number)
            )
        """)
        print("Table #3 Created Successfully.")
        
        print("\nCreating Table #4 (Locations)")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS locations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag_id INTEGER NOT NULL,
                x_coordinate REAL,
                y_coordinate REAL,
                zone_name TEXT,
                calculation_method TEXT,
                timestamp TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (tag_id) REFERENCES medicine_tags(tag_id) 
            )
        """)
        print("Table #4 Created Successfully.")
        
        print("\nCreating Table #5 (Temperature Logs)")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS temperature_logs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag_id INTEGER NOT NULL,
                temperature REAL NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (tag_id) REFERENCES medicine_tags(tag_id)
            )
        """)
        print("Table #5 Created Successfully.")
        
        print("\nCreating Table #6 (Alerts)")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alerts(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag_id INTEGER NOT NULL,
                alert_type TEXT NOT NULL,
                message TEXT NOT NULL,
                severity TEXT NOT NULL,
                timestamp TEXT DEFAULT (datetime('now')),
                acknowledged INTEGER DEFAULT 0,
                FOREIGN KEY (tag_id) REFERENCES medicine_tags(tag_id)
            )
        """)
        print("Table #6 Created Successfully.")
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print(f"\nTotal tables created: {len(tables)}")
        
        print("\nAll tables created and database setup completed successfully.")
        
    except sqlite3.Error as e:
        print(f"\nError during database setup: {e}")
        raise
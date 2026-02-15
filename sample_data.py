import sqlite3

with sqlite3.connect("hospital_iot.db") as conn:
    cursor = conn.cursor()
    
    print("Inserting sample receiver data...")
    
    cursor.execute("""
        INSERT INTO receivers (receiver_id, name, x_position, y_position, floor_level)
        VALUES (?, ?, ?, ?, ?)
    """, ('rpi4_zone_a', 'Main Ward Receiver', 5.0, 5.0, 1))
    
    print("Sample receiver inserted successfully.")
    
    cursor.execute("SELECT * FROM receivers")
    result = cursor.fetchone()
    print(f"\nReceiver: {result}")
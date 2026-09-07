import sqlite3

# Connect to your database
with sqlite3.connect("edgedash.db") as conn:
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT agent, status, notes 
        FROM cycle_log 
        WHERE status = 'failed' 
        ORDER BY started_at DESC 
        LIMIT 24
    """)
    
    print("-" * 80)
    for row in cursor.fetchall():
        print(f"Agent: {row['agent']:<20} | Notes: {row['notes']}")
    print("-" * 80)
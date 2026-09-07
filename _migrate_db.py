#!/usr/bin/env python3
"""
Migrate existing database to add the extraction_cache table.
Safe to run multiple times — uses CREATE TABLE IF NOT EXISTS.
"""

from edgedash import storage

def main():
    from edgedash.config import Config
    
    config = Config.load()
    db_path = config.db_path
    
    print(f"Migrating database: {db_path}")
    
    # Re-run init_db which will create the extraction_cache table if absent
    storage.init_db(db_path)
    
    print("✓ Database migrated successfully!")
    print("  extraction_cache table is ready.")

if __name__ == "__main__":
    main()

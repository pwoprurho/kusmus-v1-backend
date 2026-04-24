# scripts/migrate.py
"""
Kusmus AI - Database Migration Engine
Manages schema evolution by executing SQL scripts from the database/ directory.
Tracks executed migrations in a 'migrations_log' table.
"""

import os
import sys
import psycopg
from dotenv import load_dotenv

# Load env from parent dir
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

DATABASE_URL = os.getenv("DATABASE_URL")
MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), '..', 'database')

def run_migrations():
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not found in environment.")
        sys.exit(1)

    print(f"[*] Initializing migration sequence...")
    
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                # 1. Ensure migrations_log exists
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS migrations_log (
                        id SERIAL PRIMARY KEY,
                        filename TEXT UNIQUE NOT NULL,
                        applied_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                conn.commit()

                # 2. Get list of SQL files
                sql_files = [f for f in os.listdir(MIGRATIONS_DIR) if f.endswith('.sql')]
                sql_files.sort() # Ensure deterministic order

                # 3. Get already applied migrations
                cur.execute("SELECT filename FROM migrations_log;")
                applied = {row[0] for row in cur.fetchall()}

                # 4. Filter and Apply
                new_migrations = [f for f in sql_files if f not in applied]
                
                if not new_migrations:
                    print("[+] Database is already up to date.")
                    return

                print(f"[*] Found {len(new_migrations)} pending migrations.")

                for filename in new_migrations:
                    print(f"[*] Applying {filename}...")
                    filepath = os.path.join(MIGRATIONS_DIR, filename)
                    
                    with open(filepath, 'r', encoding='utf-8') as f:
                        sql = f.read()
                        
                    try:
                        # Use a subtransaction for each file
                        with conn.transaction():
                            cur.execute(sql)
                            cur.execute("INSERT INTO migrations_log (filename) VALUES (%s)", (filename,))
                        print(f"  [OK] {filename}")
                    except Exception as e:
                        print(f"  [FAILED] {filename}: {e}")
                        print("[!] Migration aborted. Fix the issue and try again.")
                        sys.exit(1)

                print(f"[SUCCESS] All migrations applied successfully.")

    except Exception as e:
        print(f"CRITICAL: Database connection failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_migrations()

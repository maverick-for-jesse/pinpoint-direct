#!/usr/bin/env python3
"""
Migration: add leads table for public marketing site sign-ups.
Safe to run multiple times (CREATE TABLE IF NOT EXISTS).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.database import get_db, get_db_type


def run():
    db_type = get_db_type()
    print(f"Running migration on: {db_type}")

    with get_db() as db:
        if db_type == 'postgres':
            with db.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS leads (
                        id            SERIAL PRIMARY KEY,
                        name          VARCHAR(255),
                        email         VARCHAR(255),
                        business_name VARCHAR(255),
                        phone         VARCHAR(50),
                        message       TEXT,
                        created_at    TIMESTAMP DEFAULT NOW()
                    )
                """)
                print("✓ leads table ready")
            db.commit()
        else:
            db.execute("""
                CREATE TABLE IF NOT EXISTS leads (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    name          TEXT,
                    email         TEXT,
                    business_name TEXT,
                    phone         TEXT,
                    message       TEXT,
                    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            db.commit()
            print("✓ leads table ready (SQLite)")

    print("\n✅ Migration complete.")


if __name__ == '__main__':
    run()

#!/usr/bin/env python3
"""
Migration: add business_profiles table + wizard columns to campaigns table.
Safe to run multiple times (all ALTER TABLEs use IF NOT EXISTS).
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
                # ── business_profiles table ──────────────────────────────────
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS business_profiles (
                        id                        SERIAL PRIMARY KEY,
                        user_id                   INTEGER REFERENCES users(id),
                        client_name               VARCHAR(255),
                        business_name             VARCHAR(255),
                        business_type             VARCHAR(100),
                        years_in_business         VARCHAR(50),
                        average_transaction_value VARCHAR(50),
                        top_services              TEXT,
                        best_customer_description TEXT,
                        customer_compliment       TEXT,
                        main_competitor           VARCHAR(255),
                        competitive_advantage     TEXT,
                        created_at                TIMESTAMP DEFAULT NOW(),
                        updated_at                TIMESTAMP DEFAULT NOW()
                    )
                """)
                print("✓ business_profiles table ready")

                # ── wizard columns on campaigns ──────────────────────────────
                wizard_cols = [
                    ("what_promoting",        "TEXT"),
                    ("offer_type",            "VARCHAR(100)"),
                    ("offer_detail",          "TEXT"),
                    ("has_deadline",          "BOOLEAN DEFAULT FALSE"),
                    ("deadline_date",         "DATE"),
                    ("desired_action",        "VARCHAR(100)"),
                    ("phone_number",          "VARCHAR(50)"),
                    ("website_url",           "VARCHAR(500)"),
                    ("target_area_description","TEXT"),
                    ("postcard_size",         "VARCHAR(20) DEFAULT '6x9'"),
                    ("estimated_quantity",    "INTEGER"),
                    ("selected_headline",     "TEXT"),
                    ("selected_body",         "TEXT"),
                    ("selected_cta",          "TEXT"),
                    ("wizard_completed",      "BOOLEAN DEFAULT FALSE"),
                    ("wizard_step",           "INTEGER DEFAULT 1"),
                ]
                for col, col_type in wizard_cols:
                    try:
                        cur.execute(f"ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS {col} {col_type}")
                        print(f"  ✓ campaigns.{col}")
                    except Exception as e:
                        print(f"  ⚠ campaigns.{col}: {e}")
            db.commit()
        else:
            # SQLite
            db.execute("""
                CREATE TABLE IF NOT EXISTS business_profiles (
                    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id                   INTEGER REFERENCES users(id),
                    client_name               TEXT,
                    business_name             TEXT,
                    business_type             TEXT,
                    years_in_business         TEXT,
                    average_transaction_value TEXT,
                    top_services              TEXT,
                    best_customer_description TEXT,
                    customer_compliment       TEXT,
                    main_competitor           TEXT,
                    competitive_advantage     TEXT,
                    created_at                DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at                DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            print("✓ business_profiles table ready")

            sqlite_cols = [
                ("what_promoting",         "TEXT"),
                ("offer_type",             "TEXT"),
                ("offer_detail",           "TEXT"),
                ("has_deadline",           "INTEGER DEFAULT 0"),
                ("deadline_date",          "DATE"),
                ("desired_action",         "TEXT"),
                ("phone_number",           "TEXT"),
                ("website_url",            "TEXT"),
                ("target_area_description","TEXT"),
                ("postcard_size",          "TEXT DEFAULT '6x9'"),
                ("estimated_quantity",     "INTEGER"),
                ("selected_headline",      "TEXT"),
                ("selected_body",          "TEXT"),
                ("selected_cta",           "TEXT"),
                ("wizard_completed",       "INTEGER DEFAULT 0"),
                ("wizard_step",            "INTEGER DEFAULT 1"),
            ]
            for col, col_type in sqlite_cols:
                try:
                    db.execute(f"ALTER TABLE campaigns ADD COLUMN {col} {col_type}")
                    print(f"  ✓ campaigns.{col}")
                except Exception as e:
                    print(f"  ⚠ campaigns.{col}: {e}")
            db.commit()

    print("\n✅ Migration complete.")

if __name__ == '__main__':
    run()

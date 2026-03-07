#!/usr/bin/env python3
"""
Create a user in the Pinpoint Direct system.
Usage: python create_user.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from werkzeug.security import generate_password_hash
from app.utils.airtable import create_record

def main():
    print("=== Create Pinpoint Direct User ===\n")
    name = input("Name: ").strip()
    email = input("Email: ").strip().lower()
    role = input("Role (Admin/Staff/Client): ").strip().capitalize()
    if role not in ('Admin', 'Staff', 'Client'):
        print("Invalid role. Must be Admin, Staff, or Client.")
        sys.exit(1)
    client = ''
    if role == 'Client':
        client = input("Client company name: ").strip()
    password = input("Password: ").strip()
    confirm = input("Confirm password: ").strip()
    if password != confirm:
        print("Passwords don't match.")
        sys.exit(1)

    password_hash = generate_password_hash(password)

    fields = {
        'Name': name,
        'Email': email,
        'Role': role,
        'Password Hash': password_hash,
    }
    if client:
        fields['Client'] = client

    record = create_record('users', fields)
    print(f"\n✅ User created: {name} ({role}) — ID: {record['id']}")

if __name__ == '__main__':
    main()

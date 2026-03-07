from flask_login import UserMixin
from werkzeug.security import check_password_hash
from app.utils.airtable import find_user_by_email, get_record, update_record
from datetime import datetime


class User(UserMixin):
    def __init__(self, record_id, name, email, role, client=None, password_hash=None):
        self.id = record_id
        self.name = name
        self.email = email
        self.role = role  # 'Admin', 'Staff', or 'Client'
        self.client = client
        self.password_hash = password_hash

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def is_admin(self):
        return self.role in ('Admin', 'Staff')

    def is_client(self):
        return self.role == 'Client'

    def update_last_login(self):
        now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')
        try:
            update_record('users', self.id, {'Last Login': now})
        except Exception:
            pass

    @staticmethod
    def get(record_id):
        try:
            record = get_record('users', record_id)
            fields = record.get('fields', {})
            return User(
                record_id=record['id'],
                name=fields.get('Name', ''),
                email=fields.get('Email', ''),
                role=fields.get('Role', 'Client'),
                client=fields.get('Client', ''),
                password_hash=fields.get('Password Hash', '')
            )
        except Exception:
            return None

    @staticmethod
    def get_by_email(email):
        record = find_user_by_email(email)
        if not record:
            return None
        fields = record.get('fields', {})
        return User(
            record_id=record['id'],
            name=fields.get('Name', ''),
            email=fields.get('Email', ''),
            role=fields.get('Role', 'Client'),
            client=fields.get('Client', ''),
            password_hash=fields.get('Password Hash', '')
        )

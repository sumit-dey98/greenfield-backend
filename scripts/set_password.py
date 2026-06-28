"""Set/reset a password for an existing student, teacher, or user row.

Usage:
    python -m scripts.set_password students std_01 mypassword123
    python -m scripts.set_password teachers tch_07 mypassword123
    python -m scripts.set_password users usr_admin_003 mypassword123
"""
import sys

from app.database import SessionLocal
from app.models import Student, Teacher, User
from app.utils import hash_password

TABLES = {"students": Student, "teachers": Teacher, "users": User}


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        return
    table, record_id, password = sys.argv[1], sys.argv[2], sys.argv[3]
    model = TABLES[table]
    db = SessionLocal()
    try:
        record = db.query(model).filter(model.id == record_id).first()
        if not record:
            print(f"No row found in {table} with id={record_id}")
            return
        record.password_hash = hash_password(password)
        db.commit()
        print(f"Password set for {table}:{record_id}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
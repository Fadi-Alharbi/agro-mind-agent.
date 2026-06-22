import json
from db.engine import SessionLocal
from db.models import Treatment

def fix_zero_day_treatments():
    db = SessionLocal()
    try:
        treatments = db.query(Treatment).all()
        fixed = 0
        deleted = 0
        for t in treatments:
            if not t.daily_tasks or t.daily_tasks == '[]':
                print(f"Deleting treatment {t.id} for {t.crop} because it has 0 tasks")
                db.delete(t)
                deleted += 1
        db.commit()
        print(f"Deleted {deleted} broken treatments.")
    finally:
        db.close()

if __name__ == "__main__":
    fix_zero_day_treatments()

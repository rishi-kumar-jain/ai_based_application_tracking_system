# """
# seed_roles.py

# Run this once after table creation to populate the roles master table.
# Can be called from your app startup or as a standalone script.

# Usage as standalone:
#     python -m app.db.seed_roles

# Usage from app startup (in main.py lifespan):
#     from app.db.seed_roles import seed_roles
#     seed_roles(db)
# """

# import logging

# from sqlalchemy.orm import Session

# from app.models.auth import Role

# logger = logging.getLogger(__name__)

# ROLES = [
#     {"role_name": "RECRUITER",   "description": "Creates JDs, runs screening, manages pipeline and assessments"},
#     {"role_name": "PANELIST",    "description": "Assigned interviewer — fills assessment ratings and uploads transcripts"},
#     {"role_name": "HR_MANAGER",  "description": "Org-wide view, approves offers, accesses all JDs and candidates"},
#     {"role_name": "ADMIN",       "description": "Full system control — manages users, roles, and system configuration"},
# ]


# def seed_roles(db: Session) -> None:
#     """
#     Inserts default roles if they don't already exist.
#     Safe to call multiple times — skips existing roles.
#     """
#     for role_data in ROLES:
#         existing = db.query(Role).filter(Role.role_name == role_data["role_name"]).first()
#         if not existing:
#             db.add(Role(**role_data))
#             logger.info("Seeded role: %s", role_data["role_name"])
#         else:
#             logger.debug("Role already exists, skipping: %s", role_data["role_name"])

#     db.commit()
#     logger.info("Role seeding complete.")


# if __name__ == "__main__":
#     from app.db.session import SessionLocal
#     db = SessionLocal()
#     try:
#         seed_roles(db)
#     finally:
#         db.close()
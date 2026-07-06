from sqlalchemy.orm import Session
from app.models.candidate import Candidate

def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip().lower()
    return value or None

# def get_or_create_candidate(db: Session, full_name: str | None, email: str | None, phone: str | None) -> Candidate:
#     norm_email = _norm(email)
#     norm_phone = _norm(phone)
#     candidate = None
#     if norm_email:
#         candidate = db.query(Candidate).filter(Candidate.email == norm_email).first()
#     if not candidate and norm_phone:
#         candidate = db.query(Candidate).filter(Candidate.phone == norm_phone).first()

#     if candidate:
#         if full_name and not candidate.full_name:
#             candidate.full_name = full_name
#         if norm_email and not candidate.email:
#             candidate.email = norm_email
#         if norm_phone and not candidate.phone:
#             candidate.phone = norm_phone
#         return candidate

#     candidate = Candidate(full_name=full_name, email=norm_email, phone=norm_phone)
#     db.add(candidate)
#     db.flush()
#     return candidate



from sqlalchemy.orm import Session
from sqlalchemy import and_

def get_or_create_candidate(
    db: Session,
    full_name: str | None,
    email: str | None,
    phone: str | None
) -> Candidate:
    name = full_name.strip() if full_name else None
    norm_email = _norm(email)
    norm_phone = _norm(phone)

    candidate = None

    # 1. Exact match: name + email + phone
    if name and norm_email and norm_phone:
        candidate = (
            db.query(Candidate)
            .filter(
                Candidate.full_name == name,
                Candidate.email == norm_email,
                Candidate.phone == norm_phone
            )
            .first()
        )

        if candidate:
            return candidate

    # 2. Match by name + email, then update phone
    if not candidate and name and norm_email:
        candidate = (
            db.query(Candidate)
            .filter(
                Candidate.full_name == name,
                Candidate.email == norm_email
            )
            .first()
        )

        if candidate:
            if norm_phone and candidate.phone != norm_phone:
                candidate.phone = norm_phone
            return candidate

    # 3. Match by name + phone, then update email
    if not candidate and name and norm_phone:
        candidate = (
            db.query(Candidate)
            .filter(
                Candidate.full_name == name,
                Candidate.phone == norm_phone
            )
            .first()
        )

        if candidate:
            if norm_email and candidate.email != norm_email:
                candidate.email = norm_email
            return candidate

    # 4. Create new candidate
    candidate = Candidate(
        full_name=name,
        email=norm_email,
        phone=norm_phone
    )

    db.add(candidate)
    db.flush()

    return candidate
"""Shared event human-verification setup for boundary tests."""

from sqlalchemy.orm import Session

from app.models.system_settings import SystemSettings


def _enforce_human_verification(db: Session) -> None:
    """Flip human_verification_enforced=True (Phase 2+) for the test DB."""
    sys_settings = db.query(SystemSettings).filter_by(id=1).first()
    if sys_settings is None:
        sys_settings = SystemSettings(id=1, human_verification_enforced=True)
        db.add(sys_settings)
    else:
        sys_settings.human_verification_enforced = True
    db.commit()

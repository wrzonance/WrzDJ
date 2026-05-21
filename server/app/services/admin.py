from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.request import Request
from app.models.user import User, UserRole
from app.services.auth import get_password_hash
from app.services.event import delete_event


def get_all_users(
    db: Session, page: int = 1, limit: int = 20, role_filter: str | None = None
) -> tuple[list[dict], int]:
    """Get paginated user list with event counts."""
    query = (
        db.query(
            User,
            func.count(Event.id).label("event_count"),
        )
        .outerjoin(Event, Event.created_by_user_id == User.id)
        .group_by(User.id)
    )

    if role_filter:
        query = query.filter(User.role == role_filter)

    total = query.count()
    offset = (page - 1) * limit
    rows = query.order_by(User.created_at.desc()).offset(offset).limit(limit).all()

    items = []
    for user, event_count in rows:
        items.append(
            {
                "id": user.id,
                "username": user.username,
                "is_active": user.is_active,
                "role": user.role,
                "created_at": user.created_at,
                "event_count": event_count,
            }
        )
    return items, total


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.query(User).filter(User.id == user_id).first()


def create_user_admin(
    db: Session, username: str, password: str, role: str = UserRole.DJ.value
) -> User:
    """Create a user with specified role (admin function)."""
    hashed_password = get_password_hash(password)
    user = User(username=username, password_hash=hashed_password, role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user_admin(
    db: Session,
    user: User,
    role: str | None = None,
    is_active: bool | None = None,
    password: str | None = None,
) -> User:
    """Update user fields (admin function)."""
    if role is not None:
        user.role = role
    if is_active is not None:
        user.is_active = is_active
    if password is not None:
        user.password_hash = get_password_hash(password)
    db.commit()
    db.refresh(user)
    return user


def count_admins(db: Session) -> int:
    """Count the number of admin users."""
    return db.query(User).filter(User.role == UserRole.ADMIN.value).count()


def delete_user(db: Session, user: User) -> None:
    """Delete a user and cascade-delete their events."""
    events = db.query(Event).filter(Event.created_by_user_id == user.id).all()
    for event in events:
        delete_event(db, event)
    db.delete(user)
    db.commit()


def get_all_events_admin(db: Session, page: int = 1, limit: int = 20) -> tuple[list[dict], int]:
    """Get paginated event list with owner info and request counts."""
    query = (
        db.query(
            Event,
            User.username.label("owner_username"),
            func.count(Request.id).label("request_count"),
        )
        .join(User, Event.created_by_user_id == User.id)
        .outerjoin(Request, Request.event_id == Event.id)
        .group_by(Event.id, User.username)
    )

    total = query.count()
    offset = (page - 1) * limit
    rows = query.order_by(Event.created_at.desc()).offset(offset).limit(limit).all()

    items = []
    for event, owner_username, request_count in rows:
        items.append(
            {
                "id": event.id,
                "code": event.code,
                "join_code": event.join_code,
                "name": event.name,
                "owner_username": owner_username,
                "owner_id": event.created_by_user_id,
                "created_at": event.created_at,
                "expires_at": event.expires_at,
                "is_active": event.is_active,
                "request_count": request_count,
            }
        )
    return items, total


def get_system_stats(db: Session) -> dict:
    """Get system-wide statistics."""
    total_users = db.query(User).count()
    active_users = (
        db.query(User)
        .filter(
            User.is_active == True,  # noqa: E712
            User.role != UserRole.PENDING.value,
        )
        .count()
    )
    pending_users = db.query(User).filter(User.role == UserRole.PENDING.value).count()
    total_events = db.query(Event).count()
    active_events = (
        db.query(Event)
        .filter(
            Event.is_active == True,  # noqa: E712
            Event.archived_at == None,  # noqa: E711
            Event.expires_at > utcnow(),
        )
        .count()
    )
    total_requests = db.query(Request).count()

    return {
        "total_users": total_users,
        "active_users": active_users,
        "pending_users": pending_users,
        "total_events": total_events,
        "active_events": active_events,
        "total_requests": total_requests,
    }

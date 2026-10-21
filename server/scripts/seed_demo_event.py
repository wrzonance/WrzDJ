"""Seed a 'demo' event with 4 enriched requests + 1 upvoted, for screenshot fixtures.

Also seeds a verified guest + per-event profile so Playwright fixtures can drop a
`wrzdj_guest` cookie and bypass the NicknameGate to capture the Tower v2 UI.
"""

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.session import SessionLocal
from app.models.event import Event
from app.models.guest import Guest
from app.models.guest_profile import GuestProfile
from app.models.request import Request as SongRequest
from app.models.user import User

DEMO_GUEST_NICKNAME = "Marcus"


def _dedupe_key(artist: str, title: str) -> str:
    return hashlib.sha1(
        f"{artist.lower()}|{title.lower()}".encode(), usedforsecurity=False
    ).hexdigest()


def reset_demo_guest(db: Session, event_id: int) -> Guest:
    """Create or refresh the local screenshot guest with a fresh bearer token."""
    profile = (
        db.query(GuestProfile)
        .filter(
            GuestProfile.event_id == event_id,
            GuestProfile.nickname == DEMO_GUEST_NICKNAME,
        )
        .first()
    )
    guest = db.get(Guest, profile.guest_id) if profile and profile.guest_id else None
    token = secrets.token_urlsafe(32)
    if guest is None:
        guest = Guest(token=token)
        db.add(guest)
    else:
        # The guest token is a bearer credential used by screenshot fixtures.
        # Rotate it on every seed run instead of keeping a public, predictable value.
        guest.token = token
    guest.email_verified_at = utcnow()
    guest.nickname = DEMO_GUEST_NICKNAME
    if profile is not None:
        profile.guest_id = guest.id
    db.flush()
    return guest


def main() -> None:
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            raise SystemExit("admin user not found")

        event = db.query(Event).filter(Event.name == "demo").first()
        if event is None:
            event = Event(
                code="DEMO01",
                name="demo",
                created_by_user_id=admin.id,
                expires_at=utcnow() + timedelta(days=7),
                is_active=True,
                requests_open=True,
            )
            db.add(event)
            db.flush()
        else:
            event.expires_at = utcnow() + timedelta(days=7)
            event.is_active = True
            event.archived_at = None

        # Force collection phase so /collect renders the leaderboard, not the live queue.
        event.collection_phase_override = "force_collection"

        db.query(SongRequest).filter(SongRequest.event_id == event.id).delete()
        db.flush()

        seeds = [
            ("Daft Punk", "One More Time", "House", 123.0, "8A", "Marcus", 0),
            ("Fred again..", "Delilah", "UK Garage", 138.0, "11A", "Jenny", 7),
            ("CamelPhat", "Cola", "Tech House", 124.0, "5A", "Tyler", 0),
            ("Disclosure", "Latch", "Future Garage", 121.0, "10B", "Sasha", 0),
        ]

        # Verified demo guest needs to exist before requests so we can link Marcus's pick.
        guest = reset_demo_guest(db, event.id)

        for artist, title, genre, bpm, key, nick, votes in seeds:
            req = SongRequest(
                event_id=event.id,
                song_title=title,
                artist=artist,
                source="manual",
                nickname=nick,
                status="new",
                genre=genre,
                bpm=bpm,
                musical_key=key,
                vote_count=votes,
                dedupe_key=_dedupe_key(artist, title),
                # Link Marcus's pick to demo guest so /join doesn't auto-open the
                # "submit a request" sheet over the screenshot.
                guest_id=guest.id if nick == DEMO_GUEST_NICKNAME else None,
                # Surface in /collect leaderboard.
                submitted_during_collection=True,
            )
            db.add(req)

        # Per-event profile (the Guest row is created above, before requests).
        profile = (
            db.query(GuestProfile)
            .filter(GuestProfile.event_id == event.id, GuestProfile.guest_id == guest.id)
            .first()
        )
        if profile is None:
            db.add(
                GuestProfile(
                    event_id=event.id,
                    guest_id=guest.id,
                    nickname=DEMO_GUEST_NICKNAME,
                    submission_count=1,
                )
            )
        else:
            profile.nickname = DEMO_GUEST_NICKNAME

        db.commit()
        print(
            f"seeded event '{event.name}' code={event.code} id={event.id} guest_token={guest.token}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()

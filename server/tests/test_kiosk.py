"""Tests for kiosk service layer."""

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.user import User
from app.services.kiosk import (
    assign_kiosk_event,
    cleanup_expired_pairing_kiosks,
    complete_pairing,
    create_kiosk,
    delete_kiosk,
    generate_pair_code,
    get_kiosk_by_id,
    get_kiosk_by_pair_code,
    get_kiosk_by_session_token,
    get_kiosks_for_user,
    is_pair_code_expired,
    rename_kiosk,
    update_kiosk_last_seen,
)


class TestGeneratePairCode:
    def test_length_is_six(self):
        code = generate_pair_code()
        assert len(code) == 6

    def test_only_safe_characters(self):
        """Should exclude O, 0, I, 1 to avoid confusion."""
        for _ in range(50):
            code = generate_pair_code()
            for char in code:
                assert char not in "O0I1"
                assert char.isalnum()

    def test_is_uppercase(self):
        for _ in range(20):
            code = generate_pair_code()
            assert code == code.upper()


class TestCreateKiosk:
    def test_creates_kiosk_with_pairing_status(self, db: Session):
        kiosk = create_kiosk(db)
        assert kiosk.status == "pairing"

    def test_session_token_is_64_chars(self, db: Session):
        kiosk = create_kiosk(db)
        assert len(kiosk.session_token) == 64

    def test_pair_code_is_6_chars(self, db: Session):
        kiosk = create_kiosk(db)
        assert len(kiosk.pair_code) == 6

    def test_expires_in_about_5_minutes(self, db: Session):
        before = utcnow()
        kiosk = create_kiosk(db)
        after = utcnow()
        # Should expire roughly 5 minutes from creation
        expected_min = before + timedelta(minutes=4, seconds=59)
        expected_max = after + timedelta(minutes=5, seconds=1)
        assert expected_min <= kiosk.pair_expires_at <= expected_max

    def test_event_code_is_null(self, db: Session):
        kiosk = create_kiosk(db)
        assert kiosk.event_code is None

    def test_paired_by_user_id_is_null(self, db: Session):
        kiosk = create_kiosk(db)
        assert kiosk.paired_by_user_id is None

    def test_unique_pair_codes(self, db: Session):
        codes = {create_kiosk(db).pair_code for _ in range(10)}
        assert len(codes) == 10

    def test_unique_session_tokens(self, db: Session):
        tokens = {create_kiosk(db).session_token for _ in range(10)}
        assert len(tokens) == 10


class TestGetKioskByPairCode:
    def test_finds_existing_kiosk(self, db: Session):
        kiosk = create_kiosk(db)
        found = get_kiosk_by_pair_code(db, kiosk.pair_code)
        assert found is not None
        assert found.id == kiosk.id

    def test_returns_none_for_unknown_code(self, db: Session):
        assert get_kiosk_by_pair_code(db, "ZZZZZZ") is None

    def test_case_insensitive(self, db: Session):
        kiosk = create_kiosk(db)
        found = get_kiosk_by_pair_code(db, kiosk.pair_code.lower())
        assert found is not None
        assert found.id == kiosk.id


class TestGetKioskBySessionToken:
    def test_finds_existing_kiosk(self, db: Session):
        kiosk = create_kiosk(db)
        found = get_kiosk_by_session_token(db, kiosk.session_token)
        assert found is not None
        assert found.id == kiosk.id

    def test_returns_none_for_unknown_token(self, db: Session):
        assert get_kiosk_by_session_token(db, "x" * 64) is None


class TestGetKioskById:
    def test_finds_existing_kiosk(self, db: Session):
        kiosk = create_kiosk(db)
        found = get_kiosk_by_id(db, kiosk.id)
        assert found is not None
        assert found.id == kiosk.id

    def test_returns_none_for_unknown_id(self, db: Session):
        assert get_kiosk_by_id(db, 99999) is None


class TestCompletePairing:
    def test_sets_active_status(self, db: Session, test_user: User, test_event: Event):
        kiosk = create_kiosk(db)
        complete_pairing(db, kiosk, test_event.code, test_user.id)
        assert kiosk.status == "active"

    def test_sets_event_code(self, db: Session, test_user: User, test_event: Event):
        kiosk = create_kiosk(db)
        complete_pairing(db, kiosk, test_event.code, test_user.id)
        assert kiosk.event_code == test_event.code

    def test_sets_user_id(self, db: Session, test_user: User, test_event: Event):
        kiosk = create_kiosk(db)
        complete_pairing(db, kiosk, test_event.code, test_user.id)
        assert kiosk.paired_by_user_id == test_user.id

    def test_sets_paired_at(self, db: Session, test_user: User, test_event: Event):
        kiosk = create_kiosk(db)
        complete_pairing(db, kiosk, test_event.code, test_user.id)
        assert kiosk.paired_at is not None

    def test_rejects_already_paired(self, db: Session, test_user: User, test_event: Event):
        kiosk = create_kiosk(db)
        complete_pairing(db, kiosk, test_event.code, test_user.id)
        with pytest.raises(ValueError, match="already paired"):
            complete_pairing(db, kiosk, test_event.code, test_user.id)

    def test_rejects_expired_code(self, db: Session, test_user: User, test_event: Event):
        kiosk = create_kiosk(db)
        # Force expiry
        kiosk.pair_expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
        with pytest.raises(ValueError, match="expired"):
            complete_pairing(db, kiosk, test_event.code, test_user.id)


class TestIsPairCodeExpired:
    def test_not_expired(self, db: Session):
        kiosk = create_kiosk(db)
        assert is_pair_code_expired(kiosk) is False

    def test_expired(self, db: Session):
        kiosk = create_kiosk(db)
        kiosk.pair_expires_at = utcnow() - timedelta(minutes=1)
        assert is_pair_code_expired(kiosk) is True


class TestUpdateKioskLastSeen:
    def test_updates_last_seen_at(self, db: Session):
        kiosk = create_kiosk(db)
        assert kiosk.last_seen_at is None
        update_kiosk_last_seen(db, kiosk)
        assert kiosk.last_seen_at is not None


class TestAssignKioskEvent:
    def test_changes_event_code(self, db: Session, test_user: User, test_event: Event):
        kiosk = create_kiosk(db)
        complete_pairing(db, kiosk, test_event.code, test_user.id)
        # Create second event
        event2 = Event(
            code="EVT002",
            join_code="WHHQ8B",
            name="Second Event",
            created_by_user_id=test_user.id,
            expires_at=utcnow() + timedelta(hours=6),
        )
        db.add(event2)
        db.commit()
        assign_kiosk_event(db, kiosk, event2.code)
        assert kiosk.event_code == "EVT002"


class TestRenameKiosk:
    def test_sets_name(self, db: Session):
        kiosk = create_kiosk(db)
        rename_kiosk(db, kiosk, "Bar Kiosk")
        assert kiosk.name == "Bar Kiosk"

    def test_clears_name_with_none(self, db: Session):
        kiosk = create_kiosk(db)
        rename_kiosk(db, kiosk, "Temp")
        rename_kiosk(db, kiosk, None)
        assert kiosk.name is None


class TestDeleteKiosk:
    def test_removes_from_db(self, db: Session):
        kiosk = create_kiosk(db)
        kiosk_id = kiosk.id
        delete_kiosk(db, kiosk)
        assert get_kiosk_by_id(db, kiosk_id) is None


class TestGetKiosksForUser:
    def test_returns_user_kiosks(self, db: Session, test_user: User, test_event: Event):
        kiosk = create_kiosk(db)
        complete_pairing(db, kiosk, test_event.code, test_user.id)
        kiosks = get_kiosks_for_user(db, test_user.id)
        assert len(kiosks) == 1
        assert kiosks[0].id == kiosk.id

    def test_excludes_other_users_kiosks(
        self, db: Session, test_user: User, admin_user: User, test_event: Event
    ):
        kiosk1 = create_kiosk(db)
        complete_pairing(db, kiosk1, test_event.code, test_user.id)
        kiosk2 = create_kiosk(db)
        complete_pairing(db, kiosk2, test_event.code, admin_user.id)
        kiosks = get_kiosks_for_user(db, test_user.id)
        assert len(kiosks) == 1
        assert kiosks[0].id == kiosk1.id

    def test_returns_empty_list_when_none(self, db: Session, test_user: User):
        kiosks = get_kiosks_for_user(db, test_user.id)
        assert kiosks == []


class TestCleanupExpiredPairingKiosks:
    def test_deletes_expired_pairing_kiosks(self, db: Session):
        kiosk = create_kiosk(db)
        kiosk.pair_expires_at = utcnow() - timedelta(minutes=10)
        db.commit()
        kiosk_id = kiosk.id
        deleted = cleanup_expired_pairing_kiosks(db)
        assert deleted >= 1
        assert get_kiosk_by_id(db, kiosk_id) is None

    def test_preserves_active_kiosks(self, db: Session, test_user: User, test_event: Event):
        kiosk = create_kiosk(db)
        complete_pairing(db, kiosk, test_event.code, test_user.id)
        # Even if pair_expires_at is past, active kiosks should not be deleted
        kiosk.pair_expires_at = utcnow() - timedelta(minutes=10)
        db.commit()
        cleanup_expired_pairing_kiosks(db)
        assert get_kiosk_by_id(db, kiosk.id) is not None

    def test_preserves_fresh_pairing_kiosks(self, db: Session):
        kiosk = create_kiosk(db)
        cleanup_expired_pairing_kiosks(db)
        assert get_kiosk_by_id(db, kiosk.id) is not None

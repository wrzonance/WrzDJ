from app.models.event import Event
from app.models.guest import Guest
from app.services.human_verification import COOKIE_NAME as HUMAN_COOKIE_NAME
from app.services.human_verification import issue_human_cookie


def _verified_guest_cookie(client, db):
    from fastapi import Response

    guest = Guest(token="frictionguest" + "0" * 51, fingerprint_hash="fp_fric")
    db.add(guest)
    db.commit()
    db.refresh(guest)
    helper = Response()
    issue_human_cookie(helper, guest.id)
    human_value = helper.headers.get("set-cookie", "").split("=", 1)[1].split(";", 1)[0]
    client.cookies.clear()
    client.cookies.set("wrzdj_guest", guest.token)
    client.cookies.set(HUMAN_COOKIE_NAME, human_value)
    return guest


def test_join_config_reports_flag(client, db, test_event: Event):
    test_event.frictionless_join = True
    db.commit()
    r = client.get(f"/api/public/collect/{test_event.code}/join-config")
    assert r.status_code == 200
    assert r.json()["frictionless_join"] is True


def test_ensure_name_autogenerates_when_frictionless(client, db, test_event: Event):
    test_event.frictionless_join = True
    db.commit()
    _verified_guest_cookie(client, db)
    r = client.post(f"/api/public/collect/{test_event.code}/guest/ensure-name", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["auto_generated"] is True
    assert body["nickname"]


def test_ensure_name_idempotent(client, db, test_event: Event):
    test_event.frictionless_join = True
    db.commit()
    _verified_guest_cookie(client, db)
    first = client.post(f"/api/public/collect/{test_event.code}/guest/ensure-name", json={}).json()
    second = client.post(f"/api/public/collect/{test_event.code}/guest/ensure-name", json={}).json()
    assert first["nickname"] == second["nickname"]


def test_ensure_name_manual_rename(client, db, test_event: Event):
    test_event.frictionless_join = True
    db.commit()
    _verified_guest_cookie(client, db)
    client.post(f"/api/public/collect/{test_event.code}/guest/ensure-name", json={})
    r = client.post(
        f"/api/public/collect/{test_event.code}/guest/ensure-name",
        json={"nickname": "MyChosenName"},
    )
    assert r.status_code == 200
    assert r.json()["nickname"] == "MyChosenName"
    assert r.json()["auto_generated"] is False


def test_ensure_name_403_when_not_frictionless(client, db, test_event: Event):
    # test_event.frictionless_join defaults False
    _verified_guest_cookie(client, db)
    r = client.post(f"/api/public/collect/{test_event.code}/guest/ensure-name", json={})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "frictionless_disabled"


def test_ensure_name_403_no_cookie_soft_mode(client, db, test_event: Event):
    """Frictionless + no wrzdj_guest cookie + soft mode -> 403 human_verification_required.

    Pins the guest_id-None guard: get_guest_id returns None without the cookie, so
    require_verified_human_soft passes None through and the endpoint must refuse
    gracefully (not 500). Regression for review finding (#369).
    """
    test_event.frictionless_join = True
    db.commit()
    client.cookies.clear()
    r = client.post(f"/api/public/collect/{test_event.code}/guest/ensure-name", json={})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "human_verification_required"

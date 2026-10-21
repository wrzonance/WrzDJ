"""Shared URL-based public playlist import preparation for REST and agent tools."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.set import Set
from app.models.set_pool import SetPoolSource
from app.models.user import User
from app.services.setbuilder import pool_sources
from app.services.setbuilder.playlist_url import InvalidPlaylistUrl, parse_public_playlist_url
from app.services.setbuilder.pool_types import PoolCandidate, PoolImportError


class UnsupportedPublicPlaylist(PoolImportError):
    """A recognized playlist URL whose provider is not supported for import."""


@dataclass(frozen=True)
class PublicPlaylistSourceIdentity:
    """Stable pool-source identity derived from one validated public playlist URL."""

    kind: str
    external_ref: str
    label: str
    meta: str


@dataclass(frozen=True)
class PreparedPublicPlaylistImport:
    """Fetched candidates and the source identity callers should persist."""

    source: PublicPlaylistSourceIdentity
    candidates: list[PoolCandidate]


def prepare_public_playlist_import(
    db: Session, user: User, url: str
) -> PreparedPublicPlaylistImport:
    """Parse a public playlist URL, fetch its candidates, and build source identity.

    No pool rows are written here. REST imports and agent turns have different
    empty-playlist and transaction policies, so callers decide when to persist
    the returned source and candidates.
    """
    parsed = parse_public_playlist_url(url)
    if not parsed.supported:
        raise UnsupportedPublicPlaylist(
            parsed.message or "That playlist provider isn't supported yet."
        )
    if parsed.playlist_id is None:
        raise InvalidPlaylistUrl("That playlist URL is missing a playlist ID.")

    if parsed.provider == "apple_music":
        if parsed.storefront is None:
            raise PoolImportError("Apple Music playlist URL is missing its storefront")
        name, candidates = pool_sources.candidates_from_public_url(
            db,
            user,
            parsed.provider,
            parsed.playlist_id,
            storefront=parsed.storefront,
        )
    else:
        name, candidates = pool_sources.candidates_from_public_url(
            db, user, parsed.provider, parsed.playlist_id
        )

    return PreparedPublicPlaylistImport(
        source=PublicPlaylistSourceIdentity(
            kind="public_url",
            external_ref=f"{parsed.provider}:{parsed.playlist_id}",
            label=name,
            meta=f"Public {parsed.provider} playlist",
        ),
        candidates=candidates,
    )


def persist_public_playlist_source(
    db: Session, set_obj: Set, prepared: PreparedPublicPlaylistImport
) -> SetPoolSource:
    """Persist the validated source identity after caller-specific checks."""
    from app.services.setbuilder.pool import get_or_create_source

    return get_or_create_source(
        db,
        set_obj,
        kind=prepared.source.kind,
        external_ref=prepared.source.external_ref,
        label=prepared.source.label,
        meta=prepared.source.meta,
    )

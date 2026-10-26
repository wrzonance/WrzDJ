"""Shared, deterministic fixtures for the CodSpeed benchmark suite.

The benchmarks only exercise pure-Python service code (no database, no
network), so fixtures build synthetic but realistic track metadata.
"""

import random

import pytest

ARTISTS = [
    "Daft Punk",
    "Fred again..",
    "Disclosure feat. Sam Smith",
    "Calvin Harris & Dua Lipa",
    "Avicii",
    "Big & Rich",
    "Rufus Du Sol",
    "Peggy Gou",
    "Darude",
    "Swedish House Mafia ft. John Martin",
    "Kaytranada x H.E.R.",
    "Fisher",
    "Chris Lake, Sammy Virji",
    "The Chemical Brothers",
    "Bicep",
    "Charlotte de Witte",
]

TITLES = [
    "One More Time",
    "Marea (We've Lost Dancing)",
    "Latch",
    "One Kiss",
    "Levels (Original Mix)",
    "Save A Horse (Ride A Cowboy)",
    "Innerbloom - Extended Mix",
    "Starry Night",
    "Sandstorm",
    "Don't You Worry Child (Radio Edit)",
    "Intimidated [feat. H.E.R.]",
    "Losing It",
    "A Little Bit of Love",
    "Galvanize (Remastered)",
    "Glue",
    "Selected (Kaiser Remix)",
    "Surrender (Hardstyle Remix)",
    "Get Low (ft. Ying Yang Twins)",
    "Blue Monday - Live",
    "Titanium (Sped Up)",
    "Workout Hits Pt. 30",
    "Strobe (Karaoke Version)",
]

KEYS = [
    "8A",
    "9B",
    "A minor",
    "C major",
    "F# min",
    "Bbm",
    "E maj",
    "11A",
    "D minor",
    "G",
    "unknown",
    None,
]

GENRES = ["Tech House", "House", "Techno", "Melodic House & Techno", "Trance", "Pop", None]


@pytest.fixture(scope="session")
def rng() -> random.Random:
    return random.Random(1337)


def make_tracks(rng: random.Random, count: int) -> list[dict]:
    tracks = []
    for i in range(count):
        tracks.append(
            {
                "title": rng.choice(TITLES),
                "artist": rng.choice(ARTISTS),
                "bpm": rng.choice([None, 64.0, 98.0, 122.0, 124.0, 126.0, 128.0, 140.0, 174.0]),
                "key": rng.choice(KEYS),
                "genre": rng.choice(GENRES),
                "isrc": f"USABC{rng.randint(0, 40):07d}" if rng.random() < 0.6 else None,
                "popularity": rng.randint(0, 100),
                "index": i,
            }
        )
    return tracks


@pytest.fixture(scope="session")
def tracks(rng: random.Random) -> list[dict]:
    return make_tracks(rng, 120)

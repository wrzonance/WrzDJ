/**
 * Serato Session File Binary Parser
 *
 * Serato DJ writes binary session files to `Music/_Serato_/History/Sessions/`
 * whenever tracks are loaded to decks. Each file contains a sequence of
 * OENT (entry) chunks, each wrapping an ADAT (attribute data) chunk with
 * track metadata encoded as tagged fields in UTF-16 Big-Endian.
 *
 * Binary format:
 *   - Each chunk: 4-byte ASCII tag + 4-byte BE length + content
 *   - OENT chunks contain nested ADAT chunks
 *   - ADAT fields: 4-byte tag + 4-byte BE length + value
 *   - Text fields are UTF-16 BE encoded (null-terminated)
 *   - Numeric fields vary (BPM is UTF-16 text of the number)
 *
 * ADAT field tags (from reverse engineering):
 *   1 = row (u32)   2 = title   6 = artist   8 = album
 *   10 = genre   13 = BPM (text)   29 = key (text)
 *   31 = added (timestamp)   45 = play time (u32)   52 = deck (u32)
 *
 * References:
 *   - https://github.com/Holzhaus/serato-tags (Rust, field documentation)
 *   - https://github.com/bkstein/SSL-API (Java, MIT)
 *   - https://github.com/whatsnowplaying/whats-now-playing (Python, MIT)
 */

import { readdirSync, statSync } from "fs";
import { join } from "path";
import { homedir, platform } from "os";

/** Parsed track entry from a Serato session file */
export interface SeratoTrackEntry {
  readonly title: string;
  readonly artist: string;
  readonly album: string;
  readonly bpm: number;
  readonly key: string;
  readonly genre: string;
  readonly deck: number;
  readonly startTime: number;
}

/**
 * ADAT field IDs mapped by their numeric tag.
 *
 * Serato uses a positional field numbering inside ADAT chunks.
 * Each field is prefixed with a u32 field ID.
 */
const FIELD_TITLE = 2;
const FIELD_ARTIST = 6;
const FIELD_ALBUM = 8;
const FIELD_GENRE = 10;
const FIELD_BPM = 13;
const FIELD_KEY = 29;
const FIELD_ADDED = 31;
const FIELD_PLAYTIME = 45;
const FIELD_DECK = 52;

/** Decode a UTF-16 Big-Endian buffer to a string, stripping null terminators. */
export function decodeUtf16BE(buf: Buffer): string {
  // Each character is 2 bytes, big-endian
  const chars: string[] = [];
  for (let i = 0; i + 1 < buf.length; i += 2) {
    const code = (buf[i]! << 8) | buf[i + 1]!;
    if (code === 0) break; // null terminator
    chars.push(String.fromCharCode(code));
  }
  return chars.join("");
}

/** Read a 4-byte ASCII tag from a buffer at the given offset. */
function readTag(buf: Buffer, offset: number): string {
  return buf.subarray(offset, offset + 4).toString("ascii");
}

/** Read a 4-byte big-endian unsigned integer. */
function readU32(buf: Buffer, offset: number): number {
  return buf.readUInt32BE(offset);
}

/**
 * Parse a single ADAT chunk's content into a SeratoTrackEntry.
 *
 * The ADAT content is a sequence of tagged fields:
 *   u32 field_id + u32 field_length + field_data
 *
 * Text fields are UTF-16 BE. Numeric fields like deck and playtime
 * are u32 integers. BPM is stored as UTF-16 text of the number.
 */
export function parseAdatContent(buf: Buffer): SeratoTrackEntry {
  let title = "";
  let artist = "";
  let album = "";
  let genre = "";
  let bpm = 0;
  let key = "";
  let deck = 0;
  let startTime = 0;

  let pos = 0;
  while (pos + 8 <= buf.length) {
    const fieldId = readU32(buf, pos);
    const fieldLen = readU32(buf, pos + 4);
    pos += 8;

    if (pos + fieldLen > buf.length) break;

    const fieldData = buf.subarray(pos, pos + fieldLen);

    switch (fieldId) {
      case FIELD_TITLE:
        title = decodeUtf16BE(fieldData);
        break;
      case FIELD_ARTIST:
        artist = decodeUtf16BE(fieldData);
        break;
      case FIELD_ALBUM:
        album = decodeUtf16BE(fieldData);
        break;
      case FIELD_GENRE:
        genre = decodeUtf16BE(fieldData);
        break;
      case FIELD_BPM: {
        const bpmText = decodeUtf16BE(fieldData);
        const parsed = parseFloat(bpmText);
        if (!Number.isNaN(parsed)) bpm = parsed;
        break;
      }
      case FIELD_KEY:
        key = decodeUtf16BE(fieldData);
        break;
      case FIELD_DECK:
        if (fieldLen >= 4) {
          deck = readU32(fieldData, 0);
        }
        break;
      case FIELD_ADDED:
        if (fieldLen >= 4) {
          startTime = readU32(fieldData, 0);
        }
        break;
      case FIELD_PLAYTIME:
        // playtime — currently unused but parsed for completeness
        break;
      default:
        // Unknown field — skip
        break;
    }

    pos += fieldLen;
  }

  return { title, artist, album, bpm, key, genre, deck, startTime };
}

/** Result of parsing session bytes, including how many bytes were fully consumed. */
export interface ParseResult {
  readonly entries: SeratoTrackEntry[];
  /** Number of bytes that were fully parsed (complete chunks only). */
  readonly bytesConsumed: number;
}

/**
 * Parse a buffer of Serato session bytes into an array of track entries.
 *
 * The session file is a sequence of top-level chunks. We look for OENT
 * chunks, each of which wraps an ADAT chunk containing track metadata.
 *
 * Returns both the parsed entries and how many bytes were fully consumed,
 * so callers can rewind the file offset to re-read incomplete chunks.
 */
export function parseSessionBytes(buf: Buffer): ParseResult {
  const entries: SeratoTrackEntry[] = [];
  let pos = 0;
  let lastCompleteChunkEnd = 0;

  while (pos + 8 <= buf.length) {
    const tag = readTag(buf, pos);
    const chunkLen = readU32(buf, pos + 4);
    pos += 8;

    if (pos + chunkLen > buf.length) {
      // Incomplete chunk — stop here; bytesConsumed stays at the last complete chunk
      break;
    }

    if (tag === "oent") {
      // OENT wraps an ADAT — look for nested ADAT chunk
      const oentEnd = pos + chunkLen;
      let innerPos = pos;

      while (innerPos + 8 <= oentEnd) {
        const innerTag = readTag(buf, innerPos);
        const innerLen = readU32(buf, innerPos + 4);
        innerPos += 8;

        if (innerPos + innerLen > oentEnd) break;

        if (innerTag === "adat") {
          const adatContent = buf.subarray(innerPos, innerPos + innerLen);
          entries.push(parseAdatContent(adatContent));
        }

        innerPos += innerLen;
      }
    }

    pos += chunkLen;
    lastCompleteChunkEnd = pos;
  }

  return { entries, bytesConsumed: lastCompleteChunkEnd };
}

/**
 * Return the OS-specific default path to Serato's session history directory.
 *
 * - macOS: ~/Music/_Serato_/History/Sessions/
 * - Windows: ~/Music/_Serato_/History/Sessions/
 * - Linux: ~/Music/_Serato_/History/Sessions/
 */
export function getDefaultSeratoPath(): string {
  const home = homedir();
  const os = platform();

  if (os === "darwin" || os === "linux") {
    return join(home, "Music", "_Serato_", "History", "Sessions");
  }

  // Windows
  return join(home, "Music", "_Serato_", "History", "Sessions");
}

/**
 * Find the most recently modified `.session` file in the given directory.
 * Returns the full path, or null if no session files exist.
 */
export function findLatestSessionFile(dir: string): string | null {
  let files: string[];
  try {
    files = readdirSync(dir);
  } catch {
    return null;
  }

  let latestPath: string | null = null;
  let latestMtime = 0;

  for (const file of files) {
    if (!file.endsWith(".session")) continue;

    const fullPath = join(dir, file);
    try {
      const stat = statSync(fullPath);
      if (stat.mtimeMs > latestMtime) {
        latestMtime = stat.mtimeMs;
        latestPath = fullPath;
      }
    } catch {
      // Skip files we can't stat
    }
  }

  return latestPath;
}

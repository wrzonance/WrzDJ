/**
 * Audio preview/embed framework for song cards.
 *
 * Provides source-specific embed URL builders for Spotify and Tidal,
 * with a consistent interface for the PreviewPlayer component.
 *
 * Beatport does not offer embeddable players — tracks from Beatport
 * can only link out to the external page.
 *
 * This module is the groundwork for issue #128.
 */

export type EmbeddableSource = 'spotify' | 'tidal';
export type PreviewSourceType = 'spotify' | 'tidal' | 'beatport';

export interface PreviewData {
  source: string;
  sourceUrl: string | null;
  previewUrl?: string | null; // Spotify 30s preview MP3
}

const SPOTIFY_TRACK_RE = /^https:\/\/open\.spotify\.com\/track\/([a-zA-Z0-9]+)/;
const TIDAL_TRACK_RE = /^https:\/\/(?:tidal\.com\/browse\/track|listen\.tidal\.com\/track)\/(\d+)/;

/**
 * Convert a Spotify track URL to its embed iframe URL.
 * Returns null if the URL isn't a valid Spotify track link.
 */
export function getSpotifyEmbedUrl(url: string | null): string | null {
  if (!url) return null;
  const match = url.match(SPOTIFY_TRACK_RE);
  if (!match) return null;
  return `https://open.spotify.com/embed/track/${match[1]}`;
}

/**
 * Convert a Tidal track URL to its embed iframe URL.
 * Returns null if the URL isn't a valid Tidal track link.
 */
export function getTidalEmbedUrl(url: string | null): string | null {
  if (!url) return null;
  const match = url.match(TIDAL_TRACK_RE);
  if (!match) return null;
  return `https://embed.tidal.com/tracks/${match[1]}`;
}

/**
 * Determine the preview source type from request/search data.
 *
 * URL pattern is the ground truth — if a URL is recognizably Tidal or
 * Beatport, we use that even when the `source` field says 'spotify'.
 * Falls back to the field when the URL doesn't match a known pattern.
 */
export function getPreviewSource(data: PreviewData): PreviewSourceType | null {
  const urlSource = detectSourceFromUrl(data.sourceUrl);
  if (urlSource) return urlSource;
  const src = data.source?.toLowerCase();
  if (src === 'spotify' || src === 'tidal') return src;
  // The Beatport branch renders an outbound link to sourceUrl, so the source
  // field alone must not label a foreign URL as Beatport.
  if (src === 'beatport' && (!data.sourceUrl || isBeatportHost(data.sourceUrl))) {
    return 'beatport';
  }
  return null;
}

/**
 * True only when the URL's host is beatport.com or a subdomain of it. A bare
 * substring test would also match `https://evil.example/?beatport.com`.
 */
function isBeatportHost(url: string): boolean {
  try {
    const host = new URL(url).hostname.toLowerCase();
    return host === 'beatport.com' || host.endsWith('.beatport.com');
  } catch {
    return false;
  }
}

function detectSourceFromUrl(url: string | null | undefined): PreviewSourceType | null {
  if (!url) return null;
  if (SPOTIFY_TRACK_RE.test(url)) return 'spotify';
  if (TIDAL_TRACK_RE.test(url)) return 'tidal';
  if (isBeatportHost(url)) return 'beatport';
  return null;
}

/**
 * Check if a track can be embedded as an audio preview.
 * Currently supports Spotify and Tidal iframe embeds.
 *
 * Uses URL pattern matching as the ground truth — even if the source
 * field is wrong, we can still embed if the URL is recognized.
 */
export function canEmbed(data: PreviewData): boolean {
  if (!data.sourceUrl) return false;
  const urlSource = detectSourceFromUrl(data.sourceUrl);
  if (urlSource === 'spotify') return true;
  if (urlSource === 'tidal') return true;
  return false;
}

/**
 * Get the embed iframe URL for a track, regardless of source field.
 * Uses URL pattern matching to determine the correct embed builder.
 */
export function getEmbedUrl(data: PreviewData): string | null {
  if (!data.sourceUrl) return null;
  const urlSource = detectSourceFromUrl(data.sourceUrl);
  if (urlSource === 'spotify') return getSpotifyEmbedUrl(data.sourceUrl);
  if (urlSource === 'tidal') return getTidalEmbedUrl(data.sourceUrl);
  return null;
}

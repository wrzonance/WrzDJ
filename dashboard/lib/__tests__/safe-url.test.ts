// @vitest-environment node
/**
 * TDD guard for H-F1 — safeExternalUrl must block dangerous URL schemes.
 *
 * @see docs/security/audit-2026-04-08.md H-F1
 */

import { describe, expect, it } from 'vitest'
import { safeExternalUrl } from '../safe-url'

describe('safeExternalUrl', () => {
  it('allows https URLs', () => {
    expect(safeExternalUrl('https://open.spotify.com/track/123')).toBe(
      'https://open.spotify.com/track/123'
    )
  })

  it('allows http URLs', () => {
    expect(safeExternalUrl('http://example.com')).toBe('http://example.com')
  })

  it('rejects javascript: URLs', () => {
    expect(safeExternalUrl('javascript:alert(1)')).toBeUndefined()
  })

  it('rejects javascript: with encoding tricks', () => {
    // Uppercase variant
    expect(safeExternalUrl('JavaScript:alert(1)')).toBeUndefined()
    // Tab insertion (URL constructor normalizes this)
    expect(safeExternalUrl('java\tscript:alert(1)')).toBeUndefined()
  })

  it('rejects data: URLs', () => {
    expect(safeExternalUrl('data:text/html,<script>alert(1)</script>')).toBeUndefined()
  })

  it('rejects vbscript: URLs', () => {
    expect(safeExternalUrl('vbscript:msgbox(1)')).toBeUndefined()
  })

  it('returns undefined for null', () => {
    expect(safeExternalUrl(null)).toBeUndefined()
  })

  it('returns undefined for undefined', () => {
    expect(safeExternalUrl(undefined)).toBeUndefined()
  })

  it('returns undefined for empty string', () => {
    expect(safeExternalUrl('')).toBeUndefined()
  })

  it('returns undefined for invalid URLs', () => {
    expect(safeExternalUrl('not a url')).toBeUndefined()
  })

  it('allows Spotify deep links over https', () => {
    expect(
      safeExternalUrl('https://open.spotify.com/track/4iV5W9uYEdYUVa79Axb7Rh')
    ).toBe('https://open.spotify.com/track/4iV5W9uYEdYUVa79Axb7Rh')
  })

  it('allows Beatport URLs', () => {
    expect(safeExternalUrl('https://www.beatport.com/track/test/12345')).toBe(
      'https://www.beatport.com/track/test/12345'
    )
  })

  it('allows Tidal URLs', () => {
    expect(safeExternalUrl('https://tidal.com/browse/track/12345')).toBe(
      'https://tidal.com/browse/track/12345'
    )
  })
})

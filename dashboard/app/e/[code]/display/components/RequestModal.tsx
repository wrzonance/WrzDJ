'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import { api, ApiError, SearchResult } from '@/lib/api';
import { KioskKeyboard } from './KioskKeyboard';

const INACTIVITY_TIMEOUT = 60000; // 60 seconds
const MAX_SEARCH_LENGTH = 200;
const MAX_NOTE_LENGTH = 500;

interface RequestModalProps {
  code: string;
  onClose: () => void;
  onRequestsClosed: () => void;
}

export function RequestModal({ code, onClose, onRequestsClosed }: RequestModalProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [selectedSong, setSelectedSong] = useState<SearchResult | null>(null);
  const [note, setNote] = useState('');
  const [nickname, setNickname] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [submitIsDuplicate, setSubmitIsDuplicate] = useState(false);
  const [submitVoteCount, setSubmitVoteCount] = useState(0);

  // Virtual keyboard detection — evaluated client-side only via useEffect.
  // Check browser touch APIs AND kiosk session token because some touchscreens
  // (e.g. ILITEK USB) present as mouse devices through Wayland compositors,
  // causing touch APIs to report false even when touch physically works.
  const [isTouch, setIsTouch] = useState(false);
  useEffect(() => {
    const hasTouch = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
    let isKiosk = false;
    try {
      isKiosk = !!localStorage.getItem('kiosk_session_token');
    } catch {
      // localStorage may be unavailable in some environments
    }
    setIsTouch(hasTouch || isKiosk);
  }, []);

  // Virtual keyboard state (touch devices only)
  const [showKeyboard, setShowKeyboard] = useState(false);
  const [activeInput, setActiveInput] = useState<'search' | 'note' | 'nickname' | null>(null);
  const submitButtonRef = useRef<HTMLButtonElement>(null);

  // Auto-show keyboard when modal opens on kiosk/touch devices, and
  // re-show for the note input when a song is selected.
  // Relying on onFocus alone is unreliable through Cage/Wayland input stacks.
  useEffect(() => {
    if (isTouch && !submitted) {
      if (selectedSong) {
        setActiveInput('nickname');
      } else {
        setActiveInput('search');
      }
      setShowKeyboard(true);
    }
  }, [isTouch, selectedSong, submitted]);

  const inactivityTimerRef = useRef<NodeJS.Timeout | null>(null);

  const closeModal = useCallback(() => {
    onClose();
  }, [onClose]);

  // Inactivity timeout
  const resetInactivityTimer = useCallback(() => {
    if (inactivityTimerRef.current) {
      clearTimeout(inactivityTimerRef.current);
    }
    inactivityTimerRef.current = setTimeout(() => {
      closeModal();
    }, INACTIVITY_TIMEOUT);
  }, [closeModal]);

  useEffect(() => {
    resetInactivityTimer();

    const handleActivity = () => resetInactivityTimer();
    window.addEventListener('touchstart', handleActivity);
    window.addEventListener('pointerdown', handleActivity);
    window.addEventListener('pointermove', handleActivity);
    window.addEventListener('keydown', handleActivity);
    return () => {
      window.removeEventListener('touchstart', handleActivity);
      window.removeEventListener('pointerdown', handleActivity);
      window.removeEventListener('pointermove', handleActivity);
      window.removeEventListener('keydown', handleActivity);
      if (inactivityTimerRef.current) {
        clearTimeout(inactivityTimerRef.current);
      }
    };
  }, [resetInactivityTimer]);

  const handleSearch = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!searchQuery.trim()) return;

    setSearching(true);
    setSearchResults([]);
    setSearchError(null);
    try {
      // Public guest endpoint — the kiosk has no DJ login. Using api.search()
      // (the DJ-only /api/search) here returned 401 and silently showed nothing.
      const results = await api.eventSearch(code, searchQuery);
      setSearchResults(results);
    } catch {
      setSearchResults([]);
      setSearchError('Search failed — please try again.');
    } finally {
      setHasSearched(true);
      setSearching(false);
    }
  };

  // Ref-stable callbacks for use in keyboard done handler
  const handleSearchRef = useRef(handleSearch);
  handleSearchRef.current = handleSearch;

  const handleSubmit = async () => {
    if (!selectedSong) return;

    setSubmitting(true);
    try {
      const result = await api.submitRequest(
        code,
        selectedSong.artist,
        selectedSong.title,
        note || undefined,
        selectedSong.url || undefined,
        selectedSong.album_art || undefined,
        undefined,
        { isrc: selectedSong.isrc || undefined },
        undefined,
        nickname || undefined,
      );
      setSubmitted(true);
      setSubmitIsDuplicate(result.is_duplicate ?? false);
      setSubmitVoteCount(result.vote_count);
      // Auto-close after 2.5 seconds
      setTimeout(() => {
        closeModal();
      }, 2500);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        closeModal();
        onRequestsClosed();
        return;
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleSubmitRef = useRef(handleSubmit);
  handleSubmitRef.current = handleSubmit;

  const hideKeyboard = useCallback(() => {
    setShowKeyboard(false);
    setActiveInput(null);
  }, []);

  const handleInputFocus = useCallback(
    (input: 'search' | 'nickname' | 'note') => {
      if (!isTouch) return;
      setActiveInput(input);
      setShowKeyboard(true);
    },
    [isTouch]
  );

  const handleKeyboardChange = useCallback(
    (value: string) => {
      if (activeInput === 'search') {
        setSearchQuery(value.slice(0, MAX_SEARCH_LENGTH));
      } else if (activeInput === 'nickname') {
        setNickname(value.slice(0, 30));
      } else if (activeInput === 'note') {
        setNote(value.slice(0, MAX_NOTE_LENGTH));
      }
    },
    [activeInput]
  );

  const handleKeyboardDone = useCallback(() => {
    if (activeInput === 'search') {
      // Keep keyboard visible so results show above it and users can refine.
      // Hiding here causes a touch-through: the synthesized click lands on the
      // overlay (behind the now-gone fixed keyboard) and closes the modal.
      handleSearchRef.current();
    } else if (activeInput === 'nickname') {
      // Advance to note input
      setActiveInput('note');
    } else if (activeInput === 'note') {
      handleSubmitRef.current();
    }
  }, [activeInput, hideKeyboard]);

  const handleSelectSong = useCallback(
    (song: SearchResult) => {
      setSelectedSong(song);
      hideKeyboard();
    },
    [hideKeyboard]
  );

  const handleBack = useCallback(() => {
    setSelectedSong(null);
    hideKeyboard();
  }, [hideKeyboard]);

  const keyboardInputValue = activeInput === 'search' ? searchQuery : activeInput === 'nickname' ? nickname : activeInput === 'note' ? note : '';
  const keyboardDoneLabel = activeInput === 'search' ? 'Search' : 'Submit';

  return (
    <div
      className={`modal-overlay${showKeyboard ? ' keyboard-overlay-active' : ''}`}
      onClick={() => {
        if (!submitting) closeModal();
      }}
    >
      <div
        className={`modal-content${showKeyboard ? ' keyboard-active' : ''}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <h2 className="modal-title">
            {submitted ? 'Success!' : selectedSong ? 'Confirm Request' : 'Request a Song'}
          </h2>
          {!submitted && (
            <button className="modal-close" onClick={closeModal}>&times;</button>
          )}
        </div>

        {submitted ? (
          <div className="success-message">
            <div className="success-icon">✓</div>
            <p className="success-text">
              {submitIsDuplicate ? 'Vote Added!' : 'Request Submitted!'}
            </p>
            {submitIsDuplicate && submitVoteCount > 0 && (
              <p className="success-vote-count">
                {submitVoteCount} {submitVoteCount === 1 ? 'person wants' : 'people want'} this song!
              </p>
            )}
          </div>
        ) : selectedSong ? (
          <div className="confirm-section">
            <div className="confirm-song">
              <h3 className="confirm-title">{selectedSong.title}</h3>
              <p className="confirm-artist">{selectedSong.artist}</p>
            </div>
            <input
              type="text"
              className="note-input"
              placeholder="Your name (optional)"
              value={nickname}
              onChange={(e) => setNickname(e.target.value)}
              onFocus={() => handleInputFocus('nickname')}
              readOnly={isTouch}
              maxLength={30}
            />
            <input
              type="text"
              className="note-input"
              placeholder="Add a note (optional)"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              onFocus={() => handleInputFocus('note')}
              readOnly={isTouch}
              maxLength={MAX_NOTE_LENGTH}
            />
            <div className="confirm-buttons">
              <button
                ref={submitButtonRef}
                className="confirm-submit"
                onClick={handleSubmit}
                disabled={submitting}
              >
                {submitting ? 'Submitting...' : 'Submit Request'}
              </button>
              <button className="confirm-back" onClick={handleBack}>
                Back
              </button>
            </div>
          </div>
        ) : (
          <>
            <form onSubmit={handleSearch} className="search-form">
              <input
                type="text"
                className="search-input"
                placeholder="Search for a song..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onFocus={() => handleInputFocus('search')}
                readOnly={isTouch}
                autoFocus={!isTouch}
              />
              <button type="submit" className="search-button" disabled={searching}>
                {searching ? '...' : 'Search'}
              </button>
            </form>
            {searchError && <p className="search-feedback search-feedback-error">{searchError}</p>}
            {!searchError && hasSearched && !searching && searchResults.length === 0 && (
              <p className="search-feedback">No songs found</p>
            )}
            {searchResults.length > 0 && (
              <div className={`search-results${showKeyboard ? ' search-results-compact' : ''}`}>
                {searchResults.map((result, index) => (
                  <button
                    key={result.spotify_id || index}
                    className="search-result-item"
                    onClick={() => handleSelectSong(result)}
                  >
                    {result.album_art ? (
                      <img
                        src={result.album_art}
                        alt={result.title}
                        className="search-result-art"
                      />
                    ) : (
                      <div className="search-result-placeholder">
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" xmlns="http://www.w3.org/2000/svg">
                          <path d="M20 4v8.5a3.5 3.5 0 1 1-2-3.163V6l-9 1.5v9a3.5 3.5 0 1 1-2-3.163V5l13-1Z" />
                        </svg>
                      </div>
                    )}
                    <div className="search-result-info">
                      <div className="search-result-title">{result.title}</div>
                      <div className="search-result-artist">{result.artist}</div>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </>
        )}

        {isTouch && showKeyboard && !submitted && (
          <KioskKeyboard
            onChange={handleKeyboardChange}
            onDone={handleKeyboardDone}
            inputValue={keyboardInputValue}
            doneLabel={keyboardDoneLabel}
            resetTimer={resetInactivityTimer}
          />
        )}
      </div>
    </div>
  );
}

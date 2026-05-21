-- ELZ2G2 ("Home School Prom 2026") data recovery — 2026-05-20
--
-- The Tidal bidirectional poller (poll_tidal_collection_removals) auto-rejected
-- 142 requests across three sweeps because get_playlist_tracks silently
-- returned [] on Tidal API failures. The fix lands in the same PR as the
-- collection/live event code split; THIS SCRIPT restores the affected rows.
--
-- USAGE (run from VPS as root or db owner, AFTER deploy.sh succeeds):
--   ssh wrz-droplet
--   cd ~/WrzDJ
--   docker compose -f deploy/docker-compose.yml exec -T db \
--     pg_dump -U wrzdj -d wrzdj -Fc -f /tmp/pre-recovery-elz2g2.dump
--   docker compose -f deploy/docker-compose.yml cp deploy/scripts/recovery-elz2g2-2026-05-20.sql db:/tmp/recovery.sql
--   docker compose -f deploy/docker-compose.yml exec -T db psql -U wrzdj -d wrzdj -f /tmp/recovery.sql
--
-- The script is wrapped in a transaction and prints sanity counts. If the
-- numbers look wrong, run ROLLBACK; instead of COMMIT;.

BEGIN;

-- Snapshot the rows we're about to touch
CREATE TEMP TABLE elz2g2_recovery AS
SELECT id, song_title, artist, status, updated_at, tidal_collection_track_id
FROM requests
WHERE event_id = 15
  AND status = 'rejected'
  AND (
    updated_at BETWEEN '2026-05-19 13:09:00' AND '2026-05-19 13:10:00'
    OR updated_at BETWEEN '2026-05-20 05:02:00' AND '2026-05-20 05:04:00'
    OR updated_at BETWEEN '2026-05-20 22:02:00' AND '2026-05-20 22:08:00'
  );

-- Expected: ~142 rows across three sweep windows
\echo 'Recovery candidates:'
SELECT COUNT(*) AS recovery_count,
       MIN(updated_at) AS earliest,
       MAX(updated_at) AS latest
FROM elz2g2_recovery;

-- Restore status='new'; bump updated_at so the polling fix has a fresh
-- baseline (now safe because the poller's three guards are deployed).
UPDATE requests
SET status = 'new', updated_at = NOW()
WHERE id IN (SELECT id FROM elz2g2_recovery);

-- Drop the lone surviving pumped vote on request #169 "Uptown Funk".
-- vote_id 362 was cast by guest 128, the cookie-cycling iPhone; see
-- 2026-05-20 production audit notes.
--
-- Decrement vote_count only when the DELETE actually removed the row, so
-- re-running this script (e.g. after a partial recovery) doesn't undercount.
WITH deleted_vote AS (
  DELETE FROM request_votes
  WHERE id = 362
  RETURNING request_id
)
UPDATE requests r
SET vote_count = GREATEST(r.vote_count - 1, 0)
FROM deleted_vote dv
WHERE r.id = dv.request_id;

-- Sanity check the resulting state.
\echo 'Post-recovery status distribution:'
SELECT status, COUNT(*) FROM requests WHERE event_id = 15 GROUP BY status ORDER BY 2 DESC;

-- Hard-guard the commit: abort if counts drift from the expected recovery shape.
DO $$
DECLARE
  recovery_count integer;
  rejected_count integer;
BEGIN
  SELECT COUNT(*) INTO recovery_count FROM elz2g2_recovery;
  SELECT COUNT(*) INTO rejected_count
  FROM requests WHERE event_id = 15 AND status = 'rejected';

  IF recovery_count BETWEEN 130 AND 150 AND rejected_count <= 5 THEN
    RAISE NOTICE 'Recovery looks correct (% rows restored, % still rejected). Committing.',
      recovery_count, rejected_count;
  ELSE
    RAISE EXCEPTION 'Recovery counts out of expected range (restored=%, still-rejected=%). Aborting.',
      recovery_count, rejected_count;
  END IF;
END
$$;

COMMIT;

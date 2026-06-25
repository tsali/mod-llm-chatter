-- Add 'whisper' event type (player whispers a bot -> in-character LLM reply).
-- Idempotent and order-independent: appends 'whisper' to the CURRENT enum
-- definition rather than re-listing every value, so it survives whatever other
-- event types have been added before it.

SET @has_whisper = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME   = 'llm_chatter_events'
    AND COLUMN_NAME  = 'event_type'
    AND COLUMN_TYPE LIKE '%''whisper''%'
);

SET @cur = (
  SELECT COLUMN_TYPE
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME   = 'llm_chatter_events'
    AND COLUMN_NAME  = 'event_type'
);

-- Replace the trailing ')' of the enum() with ",'whisper')".
SET @sql = IF(@has_whisper = 0,
  CONCAT(
    'ALTER TABLE `llm_chatter_events` MODIFY COLUMN `event_type` ',
    INSERT(@cur, LENGTH(@cur), 1, ",'whisper')"),
    ' NOT NULL'
  ),
  'SELECT 1');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

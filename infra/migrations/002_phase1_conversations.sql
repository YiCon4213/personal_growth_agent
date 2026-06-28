-- Phase 1 data migration for existing volumes.
-- The application remains a fixed single-user product; normalize legacy nullable rows.
UPDATE threads
SET user_id = 'default_user'
WHERE user_id IS NULL OR btrim(user_id) = '';

UPDATE threads
SET title = '新会话'
WHERE title IS NULL OR btrim(title) = '';
-- Phase 4: repair the legacy Phase 1 fallback title encoding while keeping
-- the fixed single-user data normalization idempotent.
UPDATE threads
SET user_id = 'default_user'
WHERE user_id IS NULL OR btrim(user_id) = '';

UPDATE threads
SET title = '新会话'
WHERE title IS NULL OR btrim(title) = '' OR title = 'ÐÂ»á»°';
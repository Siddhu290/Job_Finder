-- Per-user isolation enforced by Postgres itself (defence in depth on top of WHERE user_id = ... in every query).
-- The app runs each request in a transaction with: SELECT set_config('app.user_id', '<uuid>', true)
-- If app.user_id is not set, current_setting(..., true) is NULL and no rows are visible or writable.
-- FORCE makes the policies apply to the table owner too (Neon's app role usually owns the tables).
-- users, company_cache and serpapi_usage are not user-owned rows and are accessed only by server-side code.

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['jobs', 'job_details', 'verification', 'applications', 'history', 'runs', 'user_docs', 'run_locks']
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS user_isolation ON %I', t);
    EXECUTE format($p$CREATE POLICY user_isolation ON %I
                     USING (user_id = nullif(current_setting('app.user_id', true), '')::uuid)
                     WITH CHECK (user_id = nullif(current_setting('app.user_id', true), '')::uuid)$p$, t);
  END LOOP;
END $$;

-- Defence in depth for hosted Postgres (e.g. Neon): the login role may own the tables or even have BYPASSRLS.
-- The app therefore runs every per-user transaction as this restricted role (SET LOCAL ROLE app_rls),
-- which has no BYPASSRLS and only the table privileges it needs, so row-level security always applies.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rls') THEN
    CREATE ROLE app_rls NOLOGIN NOBYPASSRLS;
  END IF;
  EXECUTE format('GRANT app_rls TO %I', current_user);
EXCEPTION WHEN insufficient_privilege THEN
  RAISE NOTICE 'could not create role app_rls (%); the app will report RLS status at /api/health', SQLERRM;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rls') THEN
    GRANT USAGE ON SCHEMA public TO app_rls;
    GRANT SELECT, INSERT, UPDATE, DELETE ON jobs, job_details, verification, applications, history, runs, user_docs, run_locks TO app_rls;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_rls;
  END IF;
END $$;

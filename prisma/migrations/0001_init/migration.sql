-- CreateSchema
CREATE SCHEMA IF NOT EXISTS "public";

-- CreateTable
CREATE TABLE "users" (
    "id" UUID NOT NULL,
    "email" TEXT NOT NULL,
    "name" TEXT NOT NULL DEFAULT '',
    "password_hash" TEXT NOT NULL,
    "role" TEXT NOT NULL DEFAULT 'user',
    "session_version" INTEGER NOT NULL DEFAULT 1,
    "failed_logins" INTEGER NOT NULL DEFAULT 0,
    "locked_until" TIMESTAMPTZ,
    "disabled" BOOLEAN NOT NULL DEFAULT false,
    "last_run_at" TIMESTAMPTZ,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "users_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "jobs" (
    "user_id" UUID NOT NULL,
    "job_id" TEXT NOT NULL,
    "seq" BIGSERIAL NOT NULL,
    "date_found" TEXT NOT NULL DEFAULT '',
    "title" TEXT NOT NULL DEFAULT '',
    "company" TEXT NOT NULL DEFAULT '',
    "location" TEXT NOT NULL DEFAULT '',
    "experience" TEXT NOT NULL DEFAULT '',
    "employment_type" TEXT NOT NULL DEFAULT '',
    "source" TEXT NOT NULL DEFAULT '',
    "listing_url" TEXT NOT NULL DEFAULT '',
    "careers_url" TEXT NOT NULL DEFAULT '',
    "apply_url" TEXT NOT NULL DEFAULT '',
    "status" TEXT NOT NULL DEFAULT '',
    "posted_date" TEXT NOT NULL DEFAULT '',
    "last_checked" TEXT NOT NULL DEFAULT '',
    "notes" TEXT NOT NULL DEFAULT '',
    "archived" BOOLEAN NOT NULL DEFAULT false,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "jobs_pkey" PRIMARY KEY ("user_id","job_id")
);

-- CreateTable
CREATE TABLE "job_details" (
    "user_id" UUID NOT NULL,
    "job_id" TEXT NOT NULL,
    "updated" TEXT NOT NULL DEFAULT '',
    "description" TEXT NOT NULL DEFAULT '',
    "required_skills" TEXT NOT NULL DEFAULT '',
    "preferred_skills" TEXT NOT NULL DEFAULT '',
    "min_years" TEXT NOT NULL DEFAULT '',
    "education" TEXT NOT NULL DEFAULT '',
    "closes" TEXT NOT NULL DEFAULT '',
    "contacts" JSONB NOT NULL DEFAULT '[]',

    CONSTRAINT "job_details_pkey" PRIMARY KEY ("user_id","job_id")
);

-- CreateTable
CREATE TABLE "verification" (
    "id" BIGSERIAL NOT NULL,
    "user_id" UUID NOT NULL,
    "job_id" TEXT NOT NULL,
    "timestamp" TEXT NOT NULL DEFAULT '',
    "run_id" TEXT NOT NULL DEFAULT '',
    "status" TEXT NOT NULL DEFAULT '',
    "req_id" TEXT NOT NULL DEFAULT '',
    "reason" TEXT NOT NULL DEFAULT '',
    "checks" JSONB NOT NULL DEFAULT '{}',
    "last_open_check" TEXT NOT NULL DEFAULT '',
    "retry" BOOLEAN NOT NULL DEFAULT false,
    "attempts" INTEGER NOT NULL DEFAULT 0,
    "next_check" TEXT NOT NULL DEFAULT '',

    CONSTRAINT "verification_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "applications" (
    "user_id" UUID NOT NULL,
    "job_id" TEXT NOT NULL,
    "stage" TEXT NOT NULL DEFAULT '',
    "saved_date" TEXT NOT NULL DEFAULT '',
    "applied_date" TEXT NOT NULL DEFAULT '',
    "deadline" TEXT NOT NULL DEFAULT '',
    "follow_up_date" TEXT NOT NULL DEFAULT '',
    "assessment_date" TEXT NOT NULL DEFAULT '',
    "interview_date" TEXT NOT NULL DEFAULT '',
    "offer_details" TEXT NOT NULL DEFAULT '',
    "recruiter" TEXT NOT NULL DEFAULT '',
    "resume_version" TEXT NOT NULL DEFAULT '',
    "notes" TEXT NOT NULL DEFAULT '',
    "follow_up_done" TEXT NOT NULL DEFAULT '',
    "updated_at" TEXT NOT NULL DEFAULT '',

    CONSTRAINT "applications_pkey" PRIMARY KEY ("user_id","job_id")
);

-- CreateTable
CREATE TABLE "history" (
    "id" BIGSERIAL NOT NULL,
    "user_id" UUID NOT NULL,
    "timestamp" TEXT NOT NULL DEFAULT '',
    "job_id" TEXT NOT NULL DEFAULT '',
    "field" TEXT NOT NULL DEFAULT '',
    "old" TEXT NOT NULL DEFAULT '',
    "new" TEXT NOT NULL DEFAULT '',
    "action_id" TEXT NOT NULL,
    "source" TEXT NOT NULL DEFAULT '',

    CONSTRAINT "history_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "runs" (
    "run_id" TEXT NOT NULL,
    "user_id" UUID NOT NULL,
    "started" TEXT NOT NULL DEFAULT '',
    "finished" TEXT NOT NULL DEFAULT '',
    "trigger" TEXT NOT NULL DEFAULT '',
    "profile" TEXT NOT NULL DEFAULT '',
    "allowed_searches" INTEGER NOT NULL DEFAULT 0,
    "serpapi_calls" INTEGER NOT NULL DEFAULT 0,
    "discovered" INTEGER NOT NULL DEFAULT 0,
    "unique_jobs" INTEGER NOT NULL DEFAULT 0,
    "new_rows" INTEGER NOT NULL DEFAULT 0,
    "verified" INTEGER NOT NULL DEFAULT 0,
    "needs_review" INTEGER NOT NULL DEFAULT 0,
    "errors" INTEGER NOT NULL DEFAULT 0,
    "status" TEXT NOT NULL DEFAULT '',

    CONSTRAINT "runs_pkey" PRIMARY KEY ("run_id")
);

-- CreateTable
CREATE TABLE "user_docs" (
    "user_id" UUID NOT NULL,
    "kind" TEXT NOT NULL,
    "value" JSONB NOT NULL DEFAULT '{}',

    CONSTRAINT "user_docs_pkey" PRIMARY KEY ("user_id","kind")
);

-- CreateTable
CREATE TABLE "run_locks" (
    "user_id" UUID NOT NULL,
    "run_id" TEXT NOT NULL,
    "expires_at" TIMESTAMPTZ NOT NULL,

    CONSTRAINT "run_locks_pkey" PRIMARY KEY ("user_id")
);

-- CreateTable
CREATE TABLE "company_cache" (
    "key" TEXT NOT NULL,
    "value" JSONB NOT NULL,
    "updated" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "company_cache_pkey" PRIMARY KEY ("key")
);

-- CreateTable
CREATE TABLE "serpapi_usage" (
    "month" TEXT NOT NULL,
    "calls" INTEGER NOT NULL DEFAULT 0,

    CONSTRAINT "serpapi_usage_pkey" PRIMARY KEY ("month")
);

-- CreateIndex
CREATE UNIQUE INDEX "users_email_key" ON "users"("email");

-- CreateIndex
CREATE INDEX "jobs_user_id_archived_seq_idx" ON "jobs"("user_id", "archived", "seq");

-- CreateIndex
CREATE INDEX "jobs_user_id_date_found_idx" ON "jobs"("user_id", "date_found");

-- CreateIndex
CREATE INDEX "verification_user_id_job_id_id_idx" ON "verification"("user_id", "job_id", "id");

-- CreateIndex
CREATE INDEX "history_user_id_job_id_id_idx" ON "history"("user_id", "job_id", "id");

-- CreateIndex
CREATE UNIQUE INDEX "history_user_id_action_id_key" ON "history"("user_id", "action_id");

-- CreateIndex
CREATE INDEX "runs_user_id_started_idx" ON "runs"("user_id", "started");

-- AddForeignKey
ALTER TABLE "jobs" ADD CONSTRAINT "jobs_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "job_details" ADD CONSTRAINT "job_details_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "verification" ADD CONSTRAINT "verification_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "applications" ADD CONSTRAINT "applications_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "history" ADD CONSTRAINT "history_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "runs" ADD CONSTRAINT "runs_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "user_docs" ADD CONSTRAINT "user_docs_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "run_locks" ADD CONSTRAINT "run_locks_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;


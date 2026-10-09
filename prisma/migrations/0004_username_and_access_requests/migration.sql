-- AlterTable
ALTER TABLE "users" ADD COLUMN     "shared_access" TEXT NOT NULL DEFAULT 'none',
ADD COLUMN     "shared_access_decided_at" TIMESTAMPTZ,
ADD COLUMN     "shared_access_decided_by" TEXT NOT NULL DEFAULT '',
ADD COLUMN     "shared_access_message" TEXT NOT NULL DEFAULT '',
ADD COLUMN     "shared_access_requested_at" TIMESTAMPTZ,
ADD COLUMN     "username" TEXT;

-- CreateIndex
CREATE UNIQUE INDEX "users_username_key" ON "users"("username");


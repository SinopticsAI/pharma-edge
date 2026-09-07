-- Latest intake session by company or product (GET /intake/sessions).
-- Idempotent: also present in 01_cabinet.sql for a greenfield apply.

CREATE INDEX IF NOT EXISTS idx_intake_sessions_account_org_updated
    ON intake_sessions (account_id, organization_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_intake_sessions_account_product_updated
    ON intake_sessions (account_id, product_id, updated_at DESC);

-- One 统一社会信用代码 / registrationNumber per account.
-- Idempotent: also present in 01_cabinet.sql for a greenfield apply.
-- Empty cards (no number yet) stay outside the unique key.

CREATE OR REPLACE FUNCTION organization_uscc(draft jsonb, profile jsonb)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT NULLIF(upper(trim(BOTH FROM COALESCE(
    NULLIF(draft #>> '{registrationNumber,value}', ''),
    CASE WHEN jsonb_typeof(draft -> 'registrationNumber') = 'string'
         THEN NULLIF(draft ->> 'registrationNumber', '') END,
    NULLIF(profile #>> '{registrationNumber,value}', ''),
    CASE WHEN jsonb_typeof(profile -> 'registrationNumber') = 'string'
         THEN NULLIF(profile ->> 'registrationNumber', '') END,
    ''
  ))), '');
$$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_organizations_account_uscc
    ON organizations (account_id, organization_uscc(draft, profile))
    WHERE organization_uscc(draft, profile) IS NOT NULL;

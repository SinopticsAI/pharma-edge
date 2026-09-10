-- Cabinet system of record. Database pharma_cabinet, owner pharma_cabinet.
-- Apply: psql "host=c-<cluster>.rw.mdb.yandexcloud.net port=6432 dbname=pharma_cabinet
--                user=pharma_cabinet sslmode=verify-full" -f sql/01_cabinet.sql
--
-- Every table carries account_id: tenancy is enforced in queries, not hoped for.
-- Plane keeps its own roster in YDB and never writes here.

-- ---------------------------------------------------------------- identity --

-- Accounts are created by a MedMost manager; there is no self-registration.
CREATE TABLE IF NOT EXISTS accounts (
    account_id   text PRIMARY KEY,
    name         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    status       text        NOT NULL DEFAULT 'active',
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- Keycloak owns the identity, the product owns tenancy: sub resolves here.
-- Roles mirror realm roles: client | specialist | operator | admin.
CREATE TABLE IF NOT EXISTS account_users (
    subject      text PRIMARY KEY,
    account_id   text        NOT NULL REFERENCES accounts (account_id),
    role         text        NOT NULL DEFAULT 'client',
    email        text,
    display_name text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT account_users_role_check
        CHECK (role IN ('client', 'specialist', 'operator', 'admin'))
);
CREATE INDEX IF NOT EXISTS idx_account_users_account ON account_users (account_id);

-- --------------------------------------------------------------- companies --

-- status: collecting -> draft -> profile_approved.
-- profile_approved is enough to start a product; it is not enough to file.
-- draft holds provenance, not bare values:
--   {"legalName": {"value": "...", "source": "business-license p.1", "confidence": 0.94}}
CREATE TABLE IF NOT EXISTS organizations (
    organization_id text PRIMARY KEY,
    account_id      text        NOT NULL REFERENCES accounts (account_id),
    kind            text        NOT NULL DEFAULT 'cn',
    name            jsonb       NOT NULL DEFAULT '{}'::jsonb,
    status          text        NOT NULL DEFAULT 'collecting',
    draft           jsonb       NOT NULL DEFAULT '{}'::jsonb,
    profile         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT organizations_status_check
        CHECK (status IN ('collecting', 'draft', 'profile_approved'))
);
CREATE INDEX IF NOT EXISTS idx_organizations_account ON organizations (account_id);
CREATE INDEX IF NOT EXISTS idx_organizations_draft ON organizations USING gin (draft);

-- One 统一社会信用代码 per account. Empty cards have no number yet and stay free.
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

-- Legalization checklist. section groups slots into the progress panel:
-- identity | documents | authority | banking | risk.
CREATE TABLE IF NOT EXISTS organization_slots (
    organization_id  text        NOT NULL REFERENCES organizations (organization_id) ON DELETE CASCADE,
    slot_key         text        NOT NULL,
    section          text        NOT NULL DEFAULT 'documents',
    title            jsonb       NOT NULL DEFAULT '{}'::jsonb,
    requirement      jsonb,
    needs_notary     boolean     NOT NULL DEFAULT false,
    needs_apostille  boolean     NOT NULL DEFAULT false,
    needs_translation boolean    NOT NULL DEFAULT false,
    optional         boolean     NOT NULL DEFAULT false,
    status           text        NOT NULL DEFAULT 'pending',
    document_id      text,
    updated_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, slot_key),
    CONSTRAINT organization_slots_status_check
        CHECK (status IN ('pending', 'in_progress', 'filled', 'not_required'))
);

-- KYC is a gate, not a reference: a company with sanctions or fraud signals is
-- not taken on. Raw Tianyancha and court extracts stay here and are never
-- exported; the Russian side only ever sees level and the neutral reasoning.
CREATE TABLE IF NOT EXISTS company_risk_reports (
    report_id       text PRIMARY KEY,
    organization_id text        NOT NULL REFERENCES organizations (organization_id) ON DELETE CASCADE,
    account_id      text        NOT NULL REFERENCES accounts (account_id),
    level           text        NOT NULL,
    verdict         text        NOT NULL DEFAULT 'pending',
    reasoning       jsonb       NOT NULL DEFAULT '{}'::jsonb,
    checks          jsonb       NOT NULL DEFAULT '[]'::jsonb,
    raw_sources     jsonb,
    checked_by      text,
    checked_at      timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT company_risk_reports_level_check
        CHECK (level IN ('low', 'medium', 'high', 'unknown')),
    CONSTRAINT company_risk_reports_verdict_check
        CHECK (verdict IN ('pending', 'accepted', 'rejected'))
);
CREATE INDEX IF NOT EXISTS idx_company_risk_reports_org
    ON company_risk_reports (organization_id);

COMMENT ON COLUMN company_risk_reports.raw_sources IS
    'Never leaves this table. API responses expose level and reasoning only.';

-- ---------------------------------------------------------------- products --

-- status walks collecting -> draft -> data_approved -> variants_pending
--                -> variant_selected -> ru_confirmed
-- Both approvals are required before a node map is built, and the specialist
-- must come first.
CREATE TABLE IF NOT EXISTS products (
    product_id             text PRIMARY KEY,
    account_id             text        NOT NULL REFERENCES accounts (account_id),
    organization_id        text        NOT NULL REFERENCES organizations (organization_id),
    name                   jsonb       NOT NULL DEFAULT '{}'::jsonb,
    kind                   text,
    status                 text        NOT NULL DEFAULT 'collecting',
    draft                  jsonb       NOT NULL DEFAULT '{}'::jsonb,
    completeness           integer     NOT NULL DEFAULT 0,
    selected_variant_id    text,
    specialist_approved_by text,
    specialist_approved_at timestamptz,
    client_approved_by     text,
    client_approved_at     timestamptz,
    case_id                text,
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT products_status_check CHECK (status IN (
        'collecting', 'draft', 'data_approved',
        'variants_pending', 'variant_selected', 'ru_confirmed')),
    -- The client cannot approve before the specialist has.
    CONSTRAINT products_approval_order_check CHECK (
        client_approved_at IS NULL OR specialist_approved_at IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_products_org ON products (organization_id);
CREATE INDEX IF NOT EXISTS idx_products_account ON products (account_id);

-- Draft options only. variant_type = forbidden is the "do not do this" card:
-- it must be shown when the fork exists, and the platform refuses to file it.
-- Budget is three baskets in RMB, always a planning frame and never an offer.
CREATE TABLE IF NOT EXISTS classification_variants (
    variant_id    text PRIMARY KEY,
    product_id    text        NOT NULL REFERENCES products (product_id) ON DELETE CASCADE,
    account_id    text        NOT NULL REFERENCES accounts (account_id),
    variant_type  text        NOT NULL DEFAULT 'alternative',
    kind          text,
    track         text,
    risk_class    text,
    title         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    summary       jsonb       NOT NULL DEFAULT '{}'::jsonb,
    pros          jsonb       NOT NULL DEFAULT '[]'::jsonb,
    cons          jsonb       NOT NULL DEFAULT '[]'::jsonb,
    reason        jsonb,
    budget        jsonb       NOT NULL DEFAULT '{}'::jsonb,
    distribution  jsonb       NOT NULL DEFAULT '{}'::jsonb,
    cycle_months  jsonb       NOT NULL DEFAULT '[12, 18]'::jsonb,
    selected      boolean     NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT classification_variants_type_check
        CHECK (variant_type IN ('recommended', 'alternative', 'forbidden')),
    -- A forbidden option exists to be explained, never to be chosen.
    CONSTRAINT classification_variants_forbidden_check
        CHECK (NOT (selected AND variant_type = 'forbidden'))
);
CREATE INDEX IF NOT EXISTS idx_classification_variants_product
    ON classification_variants (product_id);

-- ------------------------------------------------------------------- cases --

CREATE TABLE IF NOT EXISTS cases (
    case_id           text PRIMARY KEY,
    account_id        text        NOT NULL REFERENCES accounts (account_id),
    code              text        NOT NULL,
    organization_id   text        NOT NULL REFERENCES organizations (organization_id),
    product_id        text        REFERENCES products (product_id),
    product           jsonb       NOT NULL DEFAULT '{}'::jsonb,
    manufacturer      jsonb       NOT NULL DEFAULT '{}'::jsonb,
    kind              text        NOT NULL DEFAULT 'device',
    track             text        NOT NULL DEFAULT 'pp1684',
    risk_class        text        NOT NULL DEFAULT '1',
    track_confirmed   boolean     NOT NULL DEFAULT false,
    current_stage     text        NOT NULL DEFAULT 'qualification',
    next_actor        text        NOT NULL DEFAULT 'ru',
    waiting_for       jsonb       NOT NULL DEFAULT '{}'::jsonb,
    due_working_days  integer     NOT NULL DEFAULT 30,
    started_on        date,
    cycle_months      jsonb       NOT NULL DEFAULT '[12, 18]'::jsonb,
    mandate_complete  boolean     NOT NULL DEFAULT false,
    models_locked     boolean     NOT NULL DEFAULT false,
    intake_session_id text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cases_account ON cases (account_id);
CREATE INDEX IF NOT EXISTS idx_cases_org ON cases (organization_id);

-- The 13-node map, built only after both approvals. Nodes past filing are
-- visible immediately with status 'later' so the horizon is 12-16 months.
CREATE TABLE IF NOT EXISTS node_map_items (
    case_id     text        NOT NULL REFERENCES cases (case_id) ON DELETE CASCADE,
    code        text        NOT NULL,
    position    integer     NOT NULL,
    title       jsonb       NOT NULL DEFAULT '{}'::jsonb,
    note        jsonb,
    status      text        NOT NULL DEFAULT 'later',
    owner       text        NOT NULL DEFAULT 'us',
    due_hint    jsonb,
    blocked_by  text[]      NOT NULL DEFAULT '{}',
    critical    boolean     NOT NULL DEFAULT false,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (case_id, code),
    CONSTRAINT node_map_items_status_check
        CHECK (status IN ('done', 'in_progress', 'planned', 'later', 'goal')),
    CONSTRAINT node_map_items_owner_check
        CHECK (owner IN ('you', 'us', 'contractor', 'gov'))
);

CREATE TABLE IF NOT EXISTS mandates (
    case_id     text PRIMARY KEY REFERENCES cases (case_id) ON DELETE CASCADE,
    complete    boolean     NOT NULL DEFAULT false,
    operator    text,
    role        text        NOT NULL DEFAULT 'upp',
    steps       jsonb       NOT NULL DEFAULT '[]'::jsonb,
    credentials jsonb       NOT NULL DEFAULT '[]'::jsonb,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- --------------------------------------------------------------- documents --

-- Intake documents live before and beside a case. level tells whether the file
-- belongs to the company profile or to one product; a product-level document
-- can be promoted to the company and then reaches every product of it.
CREATE TABLE IF NOT EXISTS organization_items (
    item_id          text PRIMARY KEY,
    account_id       text        NOT NULL REFERENCES accounts (account_id),
    organization_id  text        NOT NULL REFERENCES organizations (organization_id) ON DELETE CASCADE,
    product_id       text        REFERENCES products (product_id) ON DELETE SET NULL,
    level            text        NOT NULL DEFAULT 'company',
    item_type        text        NOT NULL DEFAULT 'other',
    title            jsonb       NOT NULL DEFAULT '{}'::jsonb,
    file_name        text,
    object_key       text,
    status           text        NOT NULL DEFAULT 'pending_upload',
    parced_data      jsonb,
    version          integer     NOT NULL DEFAULT 1,
    promoted_from    text,
    promoted_at      timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT organization_items_level_check CHECK (level IN ('company', 'product')),
    -- A product-level document must say which product it came from.
    CONSTRAINT organization_items_product_check
        CHECK (level = 'company' OR product_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_organization_items_org ON organization_items (organization_id);
CREATE INDEX IF NOT EXISTS idx_organization_items_product ON organization_items (product_id);
CREATE INDEX IF NOT EXISTS idx_organization_items_parced
    ON organization_items USING gin (parced_data);

-- Dossier files of a case: the pipeline contour, filled after filing starts.
CREATE TABLE IF NOT EXISTS case_items (
    item_id     text PRIMARY KEY,
    account_id  text        NOT NULL REFERENCES accounts (account_id),
    case_id     text        NOT NULL REFERENCES cases (case_id) ON DELETE CASCADE,
    item_type   text        NOT NULL DEFAULT 'other',
    title       jsonb       NOT NULL DEFAULT '{}'::jsonb,
    file_name   text,
    object_key  text,
    status      text        NOT NULL DEFAULT 'pending_upload',
    parced_data jsonb,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_case_items_case ON case_items (case_id);

-- ----------------------------------------------------------- intake dialog --

-- The chat lives on a session, not on a case: a company is added before any
-- case exists.
CREATE TABLE IF NOT EXISTS intake_sessions (
    session_id      text PRIMARY KEY,
    account_id      text        NOT NULL REFERENCES accounts (account_id),
    scope           text        NOT NULL,
    organization_id text        REFERENCES organizations (organization_id) ON DELETE CASCADE,
    product_id      text        REFERENCES products (product_id) ON DELETE CASCADE,
    status          text        NOT NULL DEFAULT 'open',
    locale          text        NOT NULL DEFAULT 'zh',
    plane_case_id   text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT intake_sessions_scope_check CHECK (scope IN ('organization', 'product'))
);
CREATE INDEX IF NOT EXISTS idx_intake_sessions_account ON intake_sessions (account_id);
CREATE INDEX IF NOT EXISTS idx_intake_sessions_account_org_updated
    ON intake_sessions (account_id, organization_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_intake_sessions_account_product_updated
    ON intake_sessions (account_id, product_id, updated_at DESC);

-- Legal history of the case, exported to the client in full. Mastra keeps its
-- own working memory in pharma_agent; this table is the record.
CREATE TABLE IF NOT EXISTS chat_messages (
    message_id text PRIMARY KEY,
    account_id text        NOT NULL REFERENCES accounts (account_id),
    session_id text        NOT NULL REFERENCES intake_sessions (session_id) ON DELETE CASCADE,
    role       text        NOT NULL,
    text       jsonb       NOT NULL DEFAULT '{}'::jsonb,
    item_id    text,
    payload    jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chat_messages_role_check CHECK (role IN ('user', 'agent', 'system'))
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session
    ON chat_messages (session_id, created_at);

CREATE TABLE IF NOT EXISTS reminders (
    reminder_id text PRIMARY KEY,
    account_id  text        NOT NULL REFERENCES accounts (account_id),
    session_id  text        REFERENCES intake_sessions (session_id) ON DELETE CASCADE,
    subject     jsonb       NOT NULL DEFAULT '{}'::jsonb,
    due_at      timestamptz NOT NULL,
    status      text        NOT NULL DEFAULT 'pending',
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders (due_at) WHERE status = 'pending';

-- ------------------------------------------------------------------- audit --

-- Every agent action is recorded with the model and prompt version behind it.
CREATE TABLE IF NOT EXISTS audit_entries (
    entry_id     text PRIMARY KEY,
    account_id   text        NOT NULL REFERENCES accounts (account_id),
    subject_type text        NOT NULL,
    subject_id   text        NOT NULL,
    action       text        NOT NULL,
    actor        text        NOT NULL,
    actor_role   text,
    detail       jsonb       NOT NULL DEFAULT '{}'::jsonb,
    model        text,
    prompt_version text,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_entries_subject
    ON audit_entries (subject_type, subject_id, created_at DESC);

-- ------------------------------------------------------ statuses and cache --

CREATE TABLE IF NOT EXISTS status_entries (
    status_id  text PRIMARY KEY,
    account_id text        NOT NULL REFERENCES accounts (account_id),
    case_id    text        NOT NULL REFERENCES cases (case_id) ON DELETE CASCADE,
    stage      text        NOT NULL,
    text       jsonb       NOT NULL DEFAULT '{}'::jsonb,
    artifact   text,
    entered_by text,
    entered_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_status_entries_case ON status_entries (case_id, entered_at DESC);

-- Poller and Hermes findings wait here until a human confirms them.
CREATE TABLE IF NOT EXISTS status_proposals (
    proposal_id text PRIMARY KEY,
    account_id  text        NOT NULL REFERENCES accounts (account_id),
    case_id     text        NOT NULL REFERENCES cases (case_id) ON DELETE CASCADE,
    kind        text        NOT NULL,
    stage       text,
    text        jsonb       NOT NULL DEFAULT '{}'::jsonb,
    status      text        NOT NULL DEFAULT 'proposed',
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_status_proposals_case ON status_proposals (case_id);

CREATE TABLE IF NOT EXISTS search_hits (
    hit_key    text PRIMARY KEY,
    source     text        NOT NULL,
    query      text        NOT NULL,
    hits       jsonb       NOT NULL DEFAULT '[]'::jsonb,
    expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS processed_messages (
    consumer     text        NOT NULL,
    message_id   text        NOT NULL,
    processed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (consumer, message_id)
);

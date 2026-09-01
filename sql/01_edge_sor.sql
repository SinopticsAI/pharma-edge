-- Edge SoR, wave 1. Prefix is table names themselves — never logos_* / verifications.
-- Apply with ydb-cli or `yc ydb scripting yql execute`.

CREATE TABLE IF NOT EXISTS organizations (
    organization_id Utf8 NOT NULL,
    kind Utf8,
    name_json Utf8,
    created_at Timestamp,
    PRIMARY KEY (organization_id)
);

CREATE TABLE IF NOT EXISTS products (
    product_id Utf8 NOT NULL,
    organization_id Utf8,
    name_json Utf8,
    kind Utf8,
    created_at Timestamp,
    PRIMARY KEY (product_id)
);

CREATE TABLE IF NOT EXISTS cases (
    case_id Utf8 NOT NULL,
    code Utf8,
    organization_id Utf8,
    product_id Utf8,
    product_json Utf8,
    manufacturer_json Utf8,
    kind Utf8,
    track Utf8,
    risk_class Utf8,
    current_stage Utf8,
    next_actor Utf8,
    waiting_for_json Utf8,
    due_working_days Int32,
    started_on Utf8,
    cycle_months_json Utf8,
    mandate_complete Bool,
    models_locked Bool,
    created_at Timestamp,
    updated_at Timestamp,
    PRIMARY KEY (case_id)
);

CREATE TABLE IF NOT EXISTS mandates (
    case_id Utf8 NOT NULL,
    complete Bool,
    operator Utf8,
    role Utf8,
    steps_json Utf8,
    credentials_json Utf8,
    updated_at Timestamp,
    PRIMARY KEY (case_id)
);

CREATE TABLE IF NOT EXISTS case_items (
    item_id Utf8 NOT NULL,
    case_id Utf8,
    item_type Utf8,
    title_json Utf8,
    file_name Utf8,
    object_key Utf8,
    status Utf8,
    parced_data Utf8,
    created_at Timestamp,
    updated_at Timestamp,
    PRIMARY KEY (item_id),
    INDEX idx_case_items_case GLOBAL ON (case_id)
);

CREATE TABLE IF NOT EXISTS search_hits (
    hit_key Utf8 NOT NULL,
    source Utf8,
    query Utf8,
    hits_json Utf8,
    expires_at Timestamp,
    created_at Timestamp,
    PRIMARY KEY (hit_key)
);

CREATE TABLE IF NOT EXISTS status_entries (
    status_id Utf8 NOT NULL,
    case_id Utf8,
    stage Utf8,
    text_json Utf8,
    artifact Utf8,
    entered_by Utf8,
    entered_at Timestamp,
    PRIMARY KEY (status_id),
    INDEX idx_status_entries_case GLOBAL ON (case_id)
);

CREATE TABLE IF NOT EXISTS status_proposals (
    proposal_id Utf8 NOT NULL,
    case_id Utf8,
    kind Utf8,
    stage Utf8,
    text_json Utf8,
    status Utf8,
    created_at Timestamp,
    PRIMARY KEY (proposal_id),
    INDEX idx_status_proposals_case GLOBAL ON (case_id)
);

CREATE TABLE IF NOT EXISTS processed_messages (
    consumer Utf8 NOT NULL,
    message_id Utf8 NOT NULL,
    processed_at Timestamp,
    PRIMARY KEY (consumer, message_id)
);

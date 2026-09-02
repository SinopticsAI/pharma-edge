-- Demo account so the cabinet has something to show before the first real one.
-- Accounts are created by a manager, never by self-registration, so seeding an
-- account here mirrors what that manager would do.

INSERT INTO accounts (account_id, name, status)
VALUES (
    'acc-demo',
    '{"ru": "Демонстрационный аккаунт", "en": "Demo account", "zh": "演示账户"}'::jsonb,
    'active'
)
ON CONFLICT (account_id) DO NOTHING;

-- Replace the subject with a real Keycloak sub from realm pharma before use.
INSERT INTO account_users (subject, account_id, role, display_name)
VALUES
    ('demo-client-subject', 'acc-demo', 'client', 'Ван Лэй'),
    ('demo-specialist-subject', 'acc-demo', 'specialist', 'Ли Цзин'),
    ('demo-operator-subject', 'acc-demo', 'operator', 'Е. Смирнова')
ON CONFLICT (subject) DO NOTHING;

INSERT INTO organizations (organization_id, account_id, kind, name, status, profile, draft)
VALUES (
    'org-cn-demo',
    'acc-demo',
    'cn',
    '{"ru": "Шэньчжэнь Минху Медикал", "en": "Shenzhen Minghu Medical", "zh": "深圳明湖医疗"}'::jsonb,
    'profile_approved',
    '{"legalName": "深圳明湖医疗", "registrationNumber": "91440300MA5G7XXXXX"}'::jsonb,
    '{"legalName": {"value": "深圳明湖医疗", "source": "business-license p.1", "confidence": 0.94},
      "registrationNumber": {"value": "91440300MA5G7XXXXX", "source": "business-license p.1", "confidence": 0.91}}'::jsonb
)
ON CONFLICT (organization_id) DO NOTHING;

INSERT INTO organizations (organization_id, account_id, kind, name, status)
VALUES (
    'org-rf-upp',
    'acc-demo',
    'rf-upp',
    '{"ru": "Российская компания группы, УПП", "en": "Russian group company, authorized representative", "zh": "集团俄罗斯公司，授权代表"}'::jsonb,
    'profile_approved'
)
ON CONFLICT (organization_id) DO NOTHING;

-- Demo account so the cabinet has something to show before the first real one.
-- Accounts are created by a manager, never by self-registration, so seeding an
-- account here mirrors what that manager would do.
--
-- Snapshot matches the manufacturer-cabinet walkthrough: Minghu, Ruikang,
-- MH-200, RK-30. Rows the SPA creates via POST /organizations land in the
-- same account and stay beside this snapshot.
--
-- Replace demo-*-subject with a real Keycloak sub from realm pharma before a
-- linked user can see this portfolio:
--   UPDATE account_users SET subject = '<keycloak-sub>'
--   WHERE subject = 'demo-client-subject';

INSERT INTO accounts (account_id, name, status)
VALUES (
  'acc-demo',
  '{"ru": "Демонстрационный аккаунт", "en": "Demo account", "zh": "演示账户"}'::jsonb,
  'active'
)
ON CONFLICT (account_id) DO NOTHING;

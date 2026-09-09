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

INSERT INTO account_users (subject, account_id, role, display_name)
VALUES
  ('demo-client-subject', 'acc-demo', 'client', '王磊'),
  ('demo-specialist-subject', 'acc-demo', 'specialist', '李静'),
  ('demo-operator-subject', 'acc-demo', 'operator', 'Е. Смирнова')
ON CONFLICT (subject) DO NOTHING;

INSERT INTO organizations (organization_id, account_id, kind, name, status, profile, draft)
VALUES (
  'org-cn-demo',
  'acc-demo',
  'cn',
  '{"zh": "深圳明湖医疗", "en": "Shenzhen Minghu Medical", "ru": "Шэньчжэнь Минху Медикал"}'::jsonb,
  'profile_approved',
  '{"legalName": "深圳明湖医疗科技有限公司", "legalNameEn": "Shenzhen Minghu Medical Co., Ltd.", "registrationNumber": "91440300MA5G7123X", "legalRepresentative": "赵敏", "address": "广东省深圳市南山区科技园", "establishedOn": "2016-04-18", "businessScope": "第二类医疗器械（体外诊断）的研发与生产", "capital": "人民币 5,000 万元"}'::jsonb,
  '{"legalName": {"value": "深圳明湖医疗科技有限公司", "source": "营业执照 · OCR", "confidence": 0.96, "verified": true}, "legalNameEn": {"value": "Shenzhen Minghu Medical Co., Ltd.", "source": "营业执照 · OCR", "confidence": 0.96, "verified": true}, "registrationNumber": {"value": "91440300MA5G7123X", "source": "营业执照 · OCR", "confidence": 0.96, "verified": true}, "legalRepresentative": {"value": "赵敏", "source": "营业执照 · OCR", "confidence": 0.96, "verified": true}, "address": {"value": "广东省深圳市南山区科技园", "source": "营业执照 · OCR", "confidence": 0.96, "verified": true}, "establishedOn": {"value": "2016-04-18", "source": "国家企业信用信息公示系统", "confidence": 0.96, "verified": true}, "businessScope": {"value": "第二类医疗器械（体外诊断）的研发与生产", "source": "营业执照 · OCR", "confidence": 0.96, "verified": true}, "capital": {"value": "人民币 5,000 万元", "source": "国家企业信用信息公示系统", "confidence": 0.96, "verified": true}}'::jsonb
)
ON CONFLICT (organization_id) DO UPDATE SET
  name = EXCLUDED.name,
  status = EXCLUDED.status,
  profile = EXCLUDED.profile,
  draft = EXCLUDED.draft,
  updated_at = now();

INSERT INTO organizations (organization_id, account_id, kind, name, status)
VALUES (
  'org-rf-upp',
  'acc-demo',
  'rf-upp',
  '{"ru": "Российская компания группы, УПП", "en": "Russian group company, authorized representative", "zh": "集团俄罗斯公司，授权代表"}'::jsonb,
  'profile_approved'
)
ON CONFLICT (organization_id) DO UPDATE SET
  name = EXCLUDED.name,
  status = EXCLUDED.status,
  updated_at = now();

INSERT INTO organizations (organization_id, account_id, kind, name, status, profile, draft)
VALUES (
  'org-cn-ruikang',
  'acc-demo',
  'cn',
  '{"zh": "杭州瑞康", "en": "Hangzhou Ruikang", "ru": "Ханчжоу Жуйкан"}'::jsonb,
  'collecting',
  '{}'::jsonb,
  '{"legalName": {"value": "杭州瑞康医疗器械有限公司", "source": "营业执照 · OCR", "confidence": 0.96, "verified": true}, "registrationNumber": {"value": "91330100MA2H8…", "source": "营业执照 · OCR", "confidence": 0.96, "verified": true}, "legalRepresentative": {"value": "周宁", "source": "营业执照 · OCR", "confidence": 0.96, "verified": true}}'::jsonb
)
ON CONFLICT (organization_id) DO UPDATE SET
  name = EXCLUDED.name,
  status = EXCLUDED.status,
  profile = EXCLUDED.profile,
  draft = EXCLUDED.draft,
  updated_at = now();

INSERT INTO products (product_id, account_id, organization_id, name, kind, status, draft, completeness)
VALUES (
  'prd-mh-200',
  'acc-demo',
  'org-cn-demo',
  '{"zh": "MH-200 血糖仪 + 试纸", "en": "MH-200 glucose meter + strips", "ru": "Глюкометр MH-200 + полоски"}'::jsonb,
  'device',
  'collecting',
  '{"name": {"value": "MH-200 血糖监测系统", "source": "NMPA / IFU §1.2", "confidence": 0.96, "verified": true}, "intendedUse": {"value": "体外诊断，患者自测血糖", "source": "IFU §1.2", "confidence": 0.96, "verified": true}, "manufacturer": {"value": "深圳明湖医疗科技有限公司", "source": "NMPA", "confidence": 0.96, "verified": true}, "sterile": {"value": "非无菌", "source": "IFU", "confidence": 0.96, "verified": true}, "nmpaNumber": {"value": "国械注准 2019…", "source": "NMPA", "confidence": 0.96, "verified": true}, "measuring": {"value": "血糖；按 257н 号令现行清单，不属于计量器具", "source": "приказ 257н · 当日核对", "confidence": 0.96, "verified": true}}'::jsonb,
  78
)
ON CONFLICT (product_id) DO UPDATE SET
  organization_id = EXCLUDED.organization_id,
  name = EXCLUDED.name,
  kind = EXCLUDED.kind,
  status = EXCLUDED.status,
  draft = EXCLUDED.draft,
  completeness = EXCLUDED.completeness,
  updated_at = now();

INSERT INTO products (product_id, account_id, organization_id, name, kind, status, draft, completeness)
VALUES (
  'prd-rk-30',
  'acc-demo',
  'org-cn-ruikang',
  '{"zh": "RK-30 血压计", "en": "RK-30 blood pressure monitor", "ru": "Тонометр RK-30"}'::jsonb,
  'device',
  'collecting',
  '{"name": {"value": "RK-30 上臂式电子血压计", "source": "说明书", "confidence": 0.96, "verified": true}, "intendedUse": {"value": "家庭血压测量", "source": "说明书", "confidence": 0.96, "verified": true}}'::jsonb,
  100
)
ON CONFLICT (product_id) DO UPDATE SET
  organization_id = EXCLUDED.organization_id,
  name = EXCLUDED.name,
  kind = EXCLUDED.kind,
  status = EXCLUDED.status,
  draft = EXCLUDED.draft,
  completeness = EXCLUDED.completeness,
  updated_at = now();

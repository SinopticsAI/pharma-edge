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

-- MH-200 walkthrough case. RK-30 stays without a case: the product hub still
-- opens, map and payments stay empty until classification is confirmed.
INSERT INTO cases (
  case_id, account_id, code, organization_id, product_id,
  product, manufacturer, kind, track, risk_class, track_confirmed,
  current_stage, next_actor, waiting_for, due_working_days,
  started_on, cycle_months, mandate_complete, models_locked
) VALUES (
  'case-mh-200',
  'acc-demo',
  'RU-0417',
  'org-cn-demo',
  'prd-mh-200',
  '{"zh": "MH-200 血糖仪 + 试纸", "en": "MH-200 glucose meter + strips", "ru": "Глюкометр MH-200 + полоски"}'::jsonb,
  '{"zh": "深圳明湖医疗", "en": "Shenzhen Minghu Medical", "ru": "Шэньчжэнь Минху Медикал"}'::jsonb,
  'device',
  'pp1684',
  '2b',
  true,
  'samples',
  'hq',
  '{"zh": "上传电安全试验协议；实验室档期保留至 18.09", "en": "Upload electrical-safety protocols; the lab slot is held until 18.09", "ru": "Загрузить протоколы электробезопасности; слот лаборатории до 18.09"}'::jsonb,
  8,
  '2025-07-01',
  '[12, 16]'::jsonb,
  true,
  true
)
ON CONFLICT (case_id) DO UPDATE SET
  code = EXCLUDED.code,
  organization_id = EXCLUDED.organization_id,
  product_id = EXCLUDED.product_id,
  product = EXCLUDED.product,
  manufacturer = EXCLUDED.manufacturer,
  kind = EXCLUDED.kind,
  track = EXCLUDED.track,
  risk_class = EXCLUDED.risk_class,
  track_confirmed = EXCLUDED.track_confirmed,
  current_stage = EXCLUDED.current_stage,
  next_actor = EXCLUDED.next_actor,
  waiting_for = EXCLUDED.waiting_for,
  due_working_days = EXCLUDED.due_working_days,
  started_on = EXCLUDED.started_on,
  cycle_months = EXCLUDED.cycle_months,
  mandate_complete = EXCLUDED.mandate_complete,
  models_locked = EXCLUDED.models_locked,
  updated_at = now();

INSERT INTO node_map_items (
  case_id, code, position, title, note, status, owner, due_hint, blocked_by, critical
) VALUES
  (
    'case-mh-200', 'M0', 0,
    '{"zh": "分类与程序", "en": "Classification and procedure", "ru": "Классификация и процедура"}'::jsonb,
    '{"zh": "2б 体外诊断，国家程序 1684，专家已确认", "en": "Class 2b IVD, national 1684, specialist confirmed", "ru": "Класс 2б ИВД, нац. 1684, утверждено специалистом"}'::jsonb,
    'done', 'us',
    '{"zh": "第 1 周", "en": "Week 1", "ru": "нед. 1"}'::jsonb,
    '{}'::text[], false
  ),
  (
    'case-mh-200', 'M1', 1,
    '{"zh": "合同与授权代表", "en": "Contract and AR", "ru": "Договор и УПП"}'::jsonb,
    '{"zh": "委托书绑定于您；更换授权代表按您的要求", "en": "POA is tied to you; AR change on your request", "ru": "Доверенность закреплена; смена УПП по требованию"}'::jsonb,
    'done', 'us',
    '{"zh": "第 2–6 周", "en": "Weeks 2–6", "ru": "нед. 2–6"}'::jsonb,
    ARRAY['M0']::text[], false
  ),
  (
    'case-mh-200', 'M2', 2,
    '{"zh": "卷宗已齐", "en": "Dossier assembled", "ru": "Досье собрано"}'::jsonb,
    '{"zh": "按 ПП 1684 第 65 条结构，版本受控", "en": "Structure per p. 65 of Decree 1684, versions controlled", "ru": "Структура по п. 65 ПП 1684"}'::jsonb,
    'done', 'us',
    '{"zh": "第 2–4 月", "en": "Months 2–4", "ru": "мес. 2–4"}'::jsonb,
    ARRAY['M1']::text[], false
  ),
  (
    'case-mh-200', 'M3', 3,
    '{"zh": "翻译与海牙认证", "en": "Translation and apostille", "ru": "Перевод и апостиль"}'::jsonb,
    '{"zh": "公司文件组：翻译 → 公证 → 海牙认证", "en": "Company set: translation → notary → apostille", "ru": "Группа задач компании"}'::jsonb,
    'done', 'us',
    '{"zh": "第 2–3 月", "en": "Months 2–3", "ru": "мес. 2–3"}'::jsonb,
    ARRAY['M2']::text[], false
  ),
  (
    'case-mh-200', 'M4', 4,
    '{"zh": "样品运抵俄罗斯", "en": "Samples to Russia", "ru": "Образцы в Россию"}'::jsonb,
    '{"zh": "201н 通知 + 海关；物流由智能体起草", "en": "Notice 201n + customs; logistics drafted by the agent", "ru": "Уведомление 201н + таможня"}'::jsonb,
    'done', 'us',
    '{"zh": "第 3 月", "en": "Month 3", "ru": "мес. 3"}'::jsonb,
    ARRAY['M2']::text[], false
  ),
  (
    'case-mh-200', 'M5', 5,
    '{"zh": "检测（ГОСТ）", "en": "Testing (GOST)", "ru": "Испытания (ГОСТ)"}'::jsonb,
    '{"zh": "等待您的 1 份文件：电安全试验协议。实验室档期保留至 18.09。NMPA/CE 报告不能替代。", "en": "Waiting for 1 file from you: electrical-safety protocols. Lab slot held until 18.09. NMPA/CE reports do not replace this.", "ru": "Ждём 1 документ — протоколы электробезопасности. Слот до 18.09."}'::jsonb,
    'in_progress', 'contractor',
    '{"zh": "至 18.09", "en": "Until 18.09", "ru": "до 18.09"}'::jsonb,
    ARRAY['M4']::text[], true
  ),
  (
    'case-mh-200', 'M6', 6,
    '{"zh": "临床评价", "en": "Clinical evaluation", "ru": "Клиническая оценка"}'::jsonb,
    '{"zh": "体外诊断无需临床试验许可，准备评价卷宗", "en": "IVD: no clinical-trial permit; evaluation dossier", "ru": "Для ИВД — без разрешения на КИ"}'::jsonb,
    'in_progress', 'contractor',
    '{"zh": "第 5–8 月", "en": "Months 5–8", "ru": "мес. 5–8"}'::jsonb,
    ARRAY['M5']::text[], false
  ),
  (
    'case-mh-200', 'M7', 7,
    '{"zh": "生产检查", "en": "Production inspection", "ru": "Инспекция производства"}'::jsonb,
    '{"zh": "ПП 135，赴深圳现场", "en": "Decree 135, visit to Shenzhen", "ru": "ПП 135, выезд в Шэньчжэнь"}'::jsonb,
    'planned', 'gov',
    '{"zh": "第 8 月", "en": "Month 8", "ru": "мес. 8"}'::jsonb,
    ARRAY['M2']::text[], false
  ),
  (
    'case-mh-200', 'M8', 8,
    '{"zh": "递交与审评（РЗН）", "en": "Filing and expertise (RZN)", "ru": "Подача и экспертиза (РЗН)"}'::jsonb,
    '{"zh": "前置节点完成后才打开；补充要求会暂停计时", "en": "Opens after predecessors; an expertise request pauses the clock", "ru": "Откроется, когда пройдены предшественники"}'::jsonb,
    'later', 'gov',
    '{"zh": "第 9–13 月", "en": "Months 9–13", "ru": "мес. 9–13"}'::jsonb,
    ARRAY['M5', 'M6', 'M7']::text[], false
  ),
  (
    'case-mh-200', 'M9', 9,
    '{"zh": "俄文标识", "en": "Russian labelling", "ru": "Русская маркировка"}'::jsonb,
    '{"zh": "俄文说明书 + 进口标签", "en": "Russian IFU + import label", "ru": "Инструкция на русском + этикетка"}'::jsonb,
    'later', 'us',
    '{"zh": "2 周", "en": "2 weeks", "ru": "2 нед."}'::jsonb,
    ARRAY['M8']::text[], false
  ),
  (
    'case-mh-200', 'M10', 10,
    '{"zh": "Честный ЗНАК", "en": "Chestny ZNAK", "ru": "Честный ЗНАК"}'::jsonb,
    '{"zh": "按当日清单核验，不写死在代码里", "en": "Checked against the list in force on the date, not hard-coded", "ru": "Сверка по актуальной редакции перечня"}'::jsonb,
    'later', 'us',
    '{"zh": "1 周", "en": "1 week", "ru": "1 нед."}'::jsonb,
    ARRAY['M9']::text[], false
  ),
  (
    'case-mh-200', 'M11', 11,
    '{"zh": "安全监测", "en": "Safety monitoring", "ru": "Мониторинг безопасности"}'::jsonb,
    '{"zh": "1113н 号令 — 授权代表义务", "en": "Order 1113n — AR duty", "ru": "Приказ 1113н — обязанность УПП"}'::jsonb,
    'later', 'us',
    '{"zh": "2 周", "en": "2 weeks", "ru": "2 нед."}'::jsonb,
    ARRAY['M8']::text[], false
  ),
  (
    'case-mh-200', 'M12', 12,
    '{"zh": "首次合法销售", "en": "First legal sale", "ru": "Первая легальная продажа"}'::jsonb,
    '{"zh": "商业进口 + 批次通知。成功标准。", "en": "Commercial import + batch notice. Success metric.", "ru": "Коммерческий импорт + уведомление о партии"}'::jsonb,
    'goal', 'you',
    '{"zh": "第 13–14 月", "en": "Months 13–14", "ru": "мес. 13–14"}'::jsonb,
    ARRAY['M9', 'M10', 'M11']::text[], false
  )
ON CONFLICT (case_id, code) DO UPDATE SET
  position = EXCLUDED.position,
  title = EXCLUDED.title,
  note = EXCLUDED.note,
  status = EXCLUDED.status,
  owner = EXCLUDED.owner,
  due_hint = EXCLUDED.due_hint,
  blocked_by = EXCLUDED.blocked_by,
  critical = EXCLUDED.critical,
  updated_at = now();

UPDATE products
SET case_id = 'case-mh-200',
    status = 'ru_confirmed',
    updated_at = now()
WHERE product_id = 'prd-mh-200';

"""Deterministic intake rules that must not be delegated to a model.

Dialogue policy lives in Mastra. What stays here is validation: how an
extraction becomes a draft field, what makes a profile sufficient, which slots
a company owes, and what the node map looks like for a chosen variant.

Draft fields carry provenance, never bare values:
    {"legalName": {"value": "...", "source": "business-license p.1",
                   "confidence": 0.94}}
A card without a source cannot be checked, and checking it is the whole point.
"""

from __future__ import annotations

from typing import Any, Optional
import json
import re

from edge_domain import ITEM_TYPES

# ------------------------------------------------------- extraction to draft --

_ORG_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "legalName": (
        "名称",
        "企业名称",
        "公司名称",
        "单位名称",
        "company_name",
        "legal_name",
        "entity_name",
        "name",
    ),
    "legalNameEn": ("company_name_en", "name_en", "english_name", "英文名称", "英文"),
    "registrationNumber": (
        "unified_social_credit_code",
        "uscc",
        "registration_number",
        "credit_code",
        "license_number",
        "统一社会信用代码",
        "社会信用代码",
        "注册号",
    ),
    "legalRepresentative": (
        "legal_representative",
        "representative",
        "legal_person",
        "法定代表人",
    ),
    "address": ("address", "registered_address", "domicile", "住所", "地址"),
    "establishedOn": (
        "establishment_date",
        "established_on",
        "registration_date",
        "成立日期",
    ),
    "businessScope": ("business_scope", "scope", "经营范围"),
    "capital": ("registered_capital", "capital", "注册资本"),
}

_PRODUCT_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("product_name", "device_name", "name", "trade_name"),
    "models": ("models", "model", "model_list", "variants"),
    "intendedUse": ("intended_use", "indications", "purpose"),
    "manufacturer": ("manufacturer", "producer", "company_name"),
    "sites": ("sites", "manufacturing_sites", "production_sites"),
    "composition": ("composition", "materials", "contact_materials"),
    "measuring": ("measuring_function", "measuring_instrument"),
    "software": ("software", "firmware"),
    "sterile": ("sterile", "sterilization"),
    "nmpaNumber": ("certificate_number", "nmpa_number", "registration_number"),
}


def _flatten(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        parts = [_flatten(item) for item in value]
        return ", ".join(part for part in parts if part)
    if isinstance(value, dict):
        for key in ("value", "ru", "en", "zh", "name"):
            if value.get(key):
                return _flatten(value[key])
        return ""
    return str(value)


_CHINESE_FIRM_RE = re.compile(r"有限责任公司|股份有限公司|有限公司|集团|厂|中心")
_LICENSE_TITLE_RE = re.compile(r"营业执照|副本|TEST FORM|SAMPLE FOR INTAKE|仅供测试|测试数据")


def _is_chinese_company_name(text: str) -> bool:
    if not text or _LICENSE_TITLE_RE.search(text):
        return False
    if not _CHINESE_FIRM_RE.search(text) or not re.search(r"[\u4e00-\u9fff]", text):
        return False
    trade = _CHINESE_FIRM_RE.sub("", text)
    return bool(re.search(r"[\u4e00-\u9fff]{2,}", trade))


# 18 characters of a 31-letter alphabet with a check digit: GB 32100-2015.
_USCC_ALPHABET = "0123456789ABCDEFGHJKLMNPQRTUWXY"
_USCC_WEIGHTS = (1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28)


def normalize_registration_number(code: Any) -> str:
    """Strip and uppercase a USCC / 注册号 so the same licence compares equal."""
    return str(code or "").strip().upper()


def uscc_looks_wrong(code: str) -> bool:
    """Whether a registration number contradicts its own check digit.

    Two scans of one licence gave two different codes, and only this arithmetic
    told them apart. Nothing downstream questions a number once it is on the
    card, so an unnoticed misread is worse here than an empty field.
    """
    value = str(code or "").strip().upper()
    # An old 15-digit 注册号 is not a USCC and must pass untouched.
    if len(value) != 18:
        return False
    total = 0
    for index, char in enumerate(value[:17]):
        position = _USCC_ALPHABET.find(char)
        # Letters the standard leaves out — I, O, S, V, Z — mean a misread, not a code.
        if position < 0:
            return True
        total += position * _USCC_WEIGHTS[index]
    remainder = 31 - (total % 31)
    return _USCC_ALPHABET[0 if remainder == 31 else remainder] != value[17]


def _pick(extracted: dict[str, Any], aliases: tuple[str, ...]) -> tuple[str, float]:
    lowered = {str(k).strip().lower(): v for k, v in extracted.items()}
    for alias in aliases:
        if alias in lowered:
            raw = lowered[alias]
            text = _flatten(raw)
            if not text:
                continue
            confidence = 0.0
            if isinstance(raw, dict):
                try:
                    confidence = float(raw.get("confidence") or 0.0)
                except (TypeError, ValueError):
                    confidence = 0.0
            return text, confidence
    return "", 0.0


def _pick_legal_name(extracted: dict[str, Any], aliases: tuple[str, ...]) -> tuple[str, float]:
    """Prefer 名称 over 英文名称 / the title 营业执照.

    samples2 prints 英文名称 above 名称. Vision often fills `name` or
    company_name with the English line first; the Chinese line is still in 名称.
    """
    lowered = {str(k).strip().lower(): v for k, v in extracted.items()}
    fallback = ("", 0.0)
    for alias in aliases:
        if alias not in lowered:
            continue
        raw = lowered[alias]
        text = _flatten(raw)
        if not text:
            continue
        confidence = 0.0
        if isinstance(raw, dict):
            try:
                confidence = float(raw.get("confidence") or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
        if _is_chinese_company_name(text):
            return text, confidence
        if not fallback[0] and not _LICENSE_TITLE_RE.search(text):
            fallback = (text, confidence)
    return fallback


def extraction_of(parced: Any) -> dict[str, Any]:
    """Plane stores {case_id, item_id, item_type, extracted, status}."""
    if isinstance(parced, str):
        try:
            parced = json.loads(parced)
        except (TypeError, ValueError):
            return {}
    if not isinstance(parced, dict):
        return {}
    for key in ("extracted", "ocr_json"):
        inner = parced.get(key)
        if isinstance(inner, dict) and inner:
            return inner
    return {
        k: v
        for k, v in parced.items()
        if k not in ("case_id", "item_id", "status", "merge_meta", "_ref", "item_type")
    }


def draft_value(draft: dict[str, Any], field: str) -> str:
    """Reads a draft field whether it carries provenance or is a bare value."""
    entry = (draft or {}).get(field)
    if isinstance(entry, dict):
        return str(entry.get("value") or "").strip()
    return str(entry or "").strip()


def registration_number_of(
    draft: dict[str, Any] | None = None,
    profile: dict[str, Any] | None = None,
) -> str:
    """The number that identifies a company card, from draft or approved profile."""
    code = normalize_registration_number(draft_value(draft or {}, "registrationNumber"))
    if code:
        return code
    return normalize_registration_number(draft_value(profile or {}, "registrationNumber"))


def plain_profile(draft: dict[str, Any]) -> dict[str, str]:
    """Approved profile keeps values only; provenance stays on the draft."""
    return {field: draft_value(draft, field) for field in (draft or {}) if draft_value(draft, field)}


def _merge(
    draft: dict[str, Any],
    parced: Any,
    aliases: dict[str, tuple[str, ...]],
    source: str,
) -> dict[str, Any]:
    extracted = extraction_of(parced)
    if not extracted:
        return dict(draft or {})
    out = dict(draft or {})
    for field, names in aliases.items():
        # Later documents fill blanks; they never overwrite what a human saw.
        if draft_value(out, field):
            continue
        value, confidence = (
            _pick_legal_name(extracted, names) if field == "legalName" else _pick(extracted, names)
        )
        if value:
            entry: dict[str, Any] = {
                "value": value,
                "source": source,
                "confidence": confidence or None,
            }
            # Filled is not the same as correct. The flag stays until a human
            # confirms the number, because approval cannot be undone upstream.
            if field == "registrationNumber" and uscc_looks_wrong(value):
                entry["verified"] = False
            out[field] = entry
    return out


def merge_org_draft(draft: dict[str, Any], parced: Any, source: str = "") -> dict[str, Any]:
    return _merge(draft, parced, _ORG_FIELD_ALIASES, source or "document")


def merge_product_draft(draft: dict[str, Any], parced: Any, source: str = "") -> dict[str, Any]:
    return _merge(draft, parced, _PRODUCT_FIELD_ALIASES, source or "document")


def missing_org_fields(draft: dict[str, Any]) -> list[str]:
    return [f for f in ("legalName", "registrationNumber") if not draft_value(draft, f)]


def suspect_org_fields(draft: dict[str, Any]) -> list[str]:
    """Fields a document filled that contradict themselves.

    Writing the field again clears it: a value typed by a person is the
    authority, and a company whose code is genuinely non-standard must not end
    up with a profile nobody can ever approve.
    """
    return [
        field
        for field, entry in (draft or {}).items()
        if isinstance(entry, dict) and entry.get("verified") is False
    ]


def l10n_text(value: Any) -> str:
    """Reads a display string from an L10n object, a draft field, or a bare value."""
    if isinstance(value, dict):
        return str(
            value.get("value") or value.get("zh") or value.get("en") or value.get("ru") or ""
        ).strip()
    return str(value or "").strip()


def product_display_name(draft: dict[str, Any], product_name: Any = None) -> str:
    """Draft name first; the card title counts when the draft line is still empty."""
    return draft_value(draft, "name") or l10n_text(product_name)


def missing_product_fields(draft: dict[str, Any], product_name: Any = None) -> list[str]:
    """Without these the agent cannot classify, so it asks for more documents."""
    missing: list[str] = []
    if not product_display_name(draft, product_name):
        missing.append("name")
    if not draft_value(draft, "intendedUse"):
        missing.append("intendedUse")
    return missing


def can_seed_fallback_variants(draft: dict[str, Any], product_name: Any = None) -> bool:
    """A display name is enough for a planning-frame draft. Completeness is not a gate."""
    return bool(product_display_name(draft, product_name))


def product_completeness(draft: dict[str, Any]) -> int:
    """Progress only. Variants need a name and an intended use, not 100."""
    wanted = ("name", "intendedUse", "models", "manufacturer", "composition", "sites")
    filled = sum(1 for field in wanted if draft_value(draft, field))
    return int(round(filled * 100 / len(wanted)))


def profile_is_sufficient(profile: Any) -> bool:
    """Enough company data to open a product. Not enough to file."""
    if not isinstance(profile, dict):
        return False
    for key in ("legalName", "registrationNumber"):
        entry = profile.get(key)
        value = entry.get("value") if isinstance(entry, dict) else entry
        if not str(value or "").strip():
            return False
    return True


def company_card_exists(org: Any) -> bool:
    """A saved draft with name and number is already a company card."""
    if not isinstance(org, dict):
        return False
    return profile_is_sufficient(org.get("profile")) or profile_is_sufficient(org.get("draft"))


def product_intake_blocked(org: Any) -> bool:
    """A product needs a company card, not a complete legalization track."""
    return not company_card_exists(org)


# ------------------------------------------------------------- company slots --

def default_org_slots() -> list[dict[str, Any]]:
    """п. 87 Правил № 1684. `section` drives the progress panel of the dialog."""
    return [
        {
            "key": "business-license",
            "section": "identity",
            "title": {
                "ru": "Свидетельство о регистрации юридического лица, 营业执照",
                "en": "Legal entity registration certificate, 营业执照",
                "zh": "法人登记证明、营业执照",
            },
            "needs_apostille": True,
            "needs_translation": True,
        },
        {
            "key": "company-registry",
            "section": "identity",
            "title": {
                "ru": "Сверка с государственным реестром КНР",
                "en": "Match against the Chinese state registry",
                "zh": "与中国国家登记簿核对",
            },
        },
        {
            "key": "poa-upp",
            "section": "authority",
            "title": {
                "ru": "Доверенность или акт назначения уполномоченного представителя",
                "en": "Power of attorney appointing the authorized representative",
                "zh": "授权委托书或授权代表任命书",
            },
            "needs_notary": True,
            "needs_apostille": True,
            "needs_translation": True,
        },
        {
            "key": "signatory",
            "section": "authority",
            "title": {
                "ru": "Доказательства полномочий подписанта, 法定代表人",
                "en": "Evidence of the signatory authority, 法定代表人",
                "zh": "签署人权限证明、法定代表人",
            },
            "needs_apostille": True,
            "needs_translation": True,
        },
        {
            "key": "site-docs",
            "section": "documents",
            "title": {
                "ru": "Документы на производственную площадку",
                "en": "Manufacturing site documents",
                "zh": "生产场地文件",
            },
            "needs_notary": True,
            "needs_apostille": True,
            "needs_translation": True,
        },
        {
            "key": "iso-13485",
            "section": "documents",
            "title": {
                "ru": "ISO 13485 и отчёт инспекции к нему",
                "en": "ISO 13485 and the related inspection report",
                "zh": "ISO 13485 及其检查报告",
            },
            "needs_notary": True,
            "needs_apostille": True,
            "needs_translation": True,
        },
        {
            "key": "bank-account",
            "section": "banking",
            "title": {
                "ru": "Банковские реквизиты для расчётов в юанях",
                "en": "Bank details for settlements in RMB",
                "zh": "人民币结算银行信息",
            },
        },
        {
            "key": "risk-check",
            "section": "risk",
            "title": {
                "ru": "Проверка рисков компании",
                "en": "Company risk check",
                "zh": "公司风险核查",
            },
        },
        {
            "key": "trademark",
            "section": "documents",
            "title": {
                "ru": "Право на товарный знак",
                "en": "Trademark right",
                "zh": "商标权",
            },
            "needs_apostille": True,
            "optional": True,
        },
    ]


def org_completeness(slots: list[dict[str, Any]]) -> dict[str, Any]:
    """Percentage plus a breakdown by section, which is what the panel shows."""
    required = [slot for slot in slots if not slot.get("optional")]
    filled = [slot for slot in required if slot.get("status") == "filled"]
    sections: dict[str, dict[str, int]] = {}
    for slot in required:
        key = str(slot.get("section") or "documents")
        bucket = sections.setdefault(key, {"filled": 0, "total": 0})
        bucket["total"] += 1
        if slot.get("status") == "filled":
            bucket["filled"] += 1
    percent = int(round(len(filled) * 100 / len(required))) if required else 0
    return {
        "filled": len(filled),
        "total": len(required),
        "percent": percent,
        "ready": bool(required) and len(filled) == len(required),
        "sections": [
            {"key": key, "filled": value["filled"], "total": value["total"]}
            for key, value in sections.items()
        ],
    }


_BANK_KEYS = ("account_number", "permit_no", "bank_name", "account_name", "开户许可证")
_SIGNATORY_KEYS = ("id_number", "citizen_id", "identity_number", "公民身份号码", "居民身份证")
_LICENSE_EXTRA_KEYS = ("registered_capital", "注册资本", "business_scope", "经营范围")
_AUTHORITY_BANK_SLOTS = ("signatory", "bank-account")


def _extracted_has(extracted: dict[str, Any], keys: tuple[str, ...]) -> bool:
    lowered = {str(key).strip().lower(): value for key, value in extracted.items()}
    for key in keys:
        value = lowered.get(key.lower())
        text = "" if value is None else str(value).strip()
        if text and text.lower() not in ("null", "none"):
            return True
    return False


def _item_blob(item_type: str, file_name: str, parced: Any) -> str:
    extracted = extraction_of(parced)
    parts = [item_type, file_name]
    for key, value in extracted.items():
        parts.append(str(key))
        parts.append("" if value is None else str(value))
    if isinstance(parced, dict):
        parts.append(str(parced.get("item_type") or ""))
        parts.append(str(parced.get("reason") or ""))
    return "\n".join(parts)


def infer_org_item_type(item_type: str = "", file_name: str = "", parced: Any = None) -> str:
    """Recover the slot type from what was read, not from the file name."""
    extracted = extraction_of(parced)
    blob = _item_blob(item_type, "", parced)
    folded = re.sub(r"\s+", "", blob.lower())

    has_bank = (
        _extracted_has(extracted, _BANK_KEYS)
        or "开户许可证" in blob
        or "itemtype=bank-account" in folded
    )
    if has_bank:
        return "bank-account"

    has_signatory = (
        _extracted_has(extracted, _SIGNATORY_KEYS)
        or "法定代表人身份证明" in blob
        or "itemtype=signatory" in folded
    )
    if has_signatory:
        return "signatory"

    current = (item_type or "").strip()
    if current in ITEM_TYPES and current not in ("other", "business-license"):
        return current

    has_license = "itemtype=business-license" in folded or (
        "营业执照" in blob and _extracted_has(extracted, _LICENSE_EXTRA_KEYS)
    )
    if has_license:
        return "business-license"

    return current if current in ITEM_TYPES else (current or "other")


def inferred_item_type_updates(items: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """(item_id, inferred_type) for company files whose stored type is wrong."""
    updates: list[tuple[str, str]] = []
    for item in items:
        if str(item.get("level") or "company") == "product":
            continue
        item_id = str(item.get("item_id") or item.get("id") or "")
        if not item_id:
            continue
        stored = str(item.get("item_type") or "")
        inferred = infer_org_item_type(stored, str(item.get("file_name") or ""), item.get("parced_data"))
        if inferred != stored and inferred != "other":
            updates.append((item_id, inferred))
    return updates


def empty_slot_fills(slots: list[dict[str, Any]], items: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """(slot_key, item_id) to close empty signatory / bank-account slots."""
    empty = {
        str(slot.get("key"))
        for slot in slots
        if slot.get("key") in _AUTHORITY_BANK_SLOTS and slot.get("status") != "filled"
    }
    fills: list[tuple[str, str]] = []
    used: set[str] = set()
    for item in items:
        if str(item.get("status") or "") != "parsed":
            continue
        if str(item.get("level") or "company") == "product":
            continue
        item_id = str(item.get("item_id") or item.get("id") or "")
        if not item_id:
            continue
        inferred = infer_org_item_type(
            str(item.get("item_type") or ""),
            str(item.get("file_name") or ""),
            item.get("parced_data"),
        )
        if inferred in empty and inferred not in used:
            fills.append((inferred, item_id))
            used.add(inferred)
    return fills


# ---------------------------------------------------- classification variants --

BUDGET_DISCLAIMER = {
    "ru": "Рамка планирования, не оферта. Решение о регистрации принимает регулятор.",
    "en": "A planning frame, not an offer. The registration decision is the regulator's.",
    "zh": "仅为规划参考，不是要约。注册决定由监管机关作出。",
}


def _budget(subscription: int, handling: int, pass_through: int) -> dict[str, Any]:
    """Three baskets in RMB. There is never a single 'total to pay' line."""
    return {
        "currency": "RMB",
        "baskets": [
            {"key": "subscription", "amount": subscription},
            {"key": "handling", "amount": handling},
            {"key": "pass-through", "amount": pass_through},
        ],
        "disclaimer": dict(BUDGET_DISCLAIMER),
    }


def _l10n(ru: str, en: str, zh: str) -> dict[str, str]:
    return {"ru": ru, "en": en, "zh": zh}


_FALLBACK_VARIANTS: dict[str, list[dict[str, Any]]] = {
    "device": [
        {
            "variant_type": "recommended",
            "kind": "device",
            "track": "pp1684",
            "risk_class": "2b",
            "title": _l10n(
                "Национальный трек, ПП РФ № 1684",
                "National track, RF Decree No. 1684",
                "国家路径，俄联邦第 1684 号决议",
            ),
            "summary": _l10n(
                "Технические испытания, клиническая оценка, инспекция производства по ПП 135, заявление 630782.",
                "Technical tests, clinical evaluation, manufacturing inspection under Decree 135, application 630782.",
                "技术检测、临床评价、按第 135 号决议进行生产检查、630782 申请。",
            ),
            "pros": [
                _l10n("Бессрочное удостоверение", "Open-ended authorization", "注册证无期限"),
                _l10n("Досье конвертируемо в ЕАЭС", "Dossier convertible to EAEU", "档案可转为欧亚经济联盟"),
            ],
            "cons": [
                _l10n("Действует только в России", "Valid in Russia only", "仅在俄罗斯有效"),
                _l10n("Класс 2б требует инспекции", "Class 2b requires an inspection", "2b 类需要检查"),
            ],
            "budget": _budget(4150, 12800, 32433),
            "cycle_months": [12, 16],
        },
        {
            "variant_type": "alternative",
            "kind": "device",
            "track": "eaeu46",
            "risk_class": "2b",
            "title": _l10n(
                "Союзный трек, Решение № 46",
                "Union track, Decision No. 46",
                "联盟路径，第 46 号决定",
            ),
            "summary": _l10n(
                "Одно удостоверение на государства союза, отдельная услуга 613264, дольше и дороже.",
                "One authorization across the Union, separate service 613264, longer and costlier.",
                "一份注册证覆盖联盟国家，单独服务 613264，周期更长、成本更高。",
            ),
            "pros": [_l10n("Признание в государствах союза", "Recognition across member states", "成员国互认")],
            "cons": [_l10n("Дольше и дороже", "Longer and costlier", "周期更长、成本更高")],
            "budget": _budget(4150, 16400, 41200),
            "cycle_months": [14, 20],
        },
        {
            "variant_type": "forbidden",
            "kind": "device",
            "track": "pp1684",
            "risk_class": "2a",
            "title": _l10n(
                "Заявить класс 2а, чтобы сэкономить",
                "File as class 2a to cut cost",
                "申报 2а 以降低费用",
            ),
            "summary": _l10n(
                "Пошлина ниже и нет инспекции, но заниженный класс вернётся с экспертизы: потеря месяцев и пошлины. Платформа это не подаёт.",
                "A lower fee and no inspection, but an understated class comes back from review — months and the fee lost. The platform will not file this.",
                "规费更低且无生产检查，但低报类别会被审评退回，损失数月与规费。平台不会申报此项。",
            ),
            "pros": [],
            "cons": [_l10n("Досье вернут", "The dossier will be returned", "卷宗将被退回")],
            "reason": _l10n(
                "Мы это не подаём.",
                "We will not file this.",
                "我们不会申报此项。",
            ),
            "budget": _budget(0, 0, 0),
            "cycle_months": [12, 16],
        },
    ],
    "drug": [
        {
            "variant_type": "recommended",
            "kind": "drug",
            "track": "eaeu78",
            "risk_class": "1",
            "title": _l10n(
                "Решение № 78, РФ как референтное государство",
                "Decision No. 78, Russia as the reference state",
                "第 78 号决定，以俄罗斯为参照国",
            ),
            "summary": _l10n(
                "Досье ОТД, контроль качества, биоэквивалентность, инспекция площадки, экспертиза до 140 рабочих дней.",
                "eCTD dossier, quality control, bioequivalence, site inspection, review up to 140 working days.",
                "ОТД 档案、质量控制、生物等效性、场地检查，审评最长 140 个工作日。",
            ),
            "budget": _budget(4150, 26000, 96000),
            "cycle_months": [18, 26],
        },
    ],
}


def fallback_variants(kind: str) -> list[dict[str, Any]]:
    """Planning-frame draft when the agent has not written options yet."""
    key = kind if kind in _FALLBACK_VARIANTS else "device"
    return [dict(item) for item in _FALLBACK_VARIANTS[key]]


def variants_from_report(report: Any, kind: str) -> tuple[list[dict[str, Any]], bool]:
    """Reads the qualify agent report. Returns (variants, escalate)."""
    if not isinstance(report, dict):
        return fallback_variants(kind), False

    escalate = False
    for check in report.get("checks") or []:
        if not isinstance(check, dict):
            continue
        if str(check.get("name") or "").strip() == "escalation" and check.get("result") == "fail":
            escalate = True

    raw = report.get("variants")
    if not isinstance(raw, list) or not raw:
        return fallback_variants(kind), escalate

    out: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        variant_kind = str(entry.get("kind") or kind or "device")
        base = fallback_variants(variant_kind)[0]
        variant_type = str(entry.get("variant_type") or entry.get("variantType") or "alternative")
        if variant_type not in ("recommended", "alternative", "forbidden"):
            variant_type = "alternative"
        out.append(
            {
                "variant_type": variant_type,
                "kind": variant_kind,
                "track": str(entry.get("track") or base["track"]),
                "risk_class": str(entry.get("risk_class") or entry.get("riskClass") or base["risk_class"]),
                "title": entry.get("title") or base["title"],
                "summary": entry.get("summary") or base["summary"],
                "pros": entry.get("pros") or [],
                "cons": entry.get("cons") or [],
                "reason": entry.get("reason"),
                "budget": entry.get("budget") or base["budget"],
                "distribution": entry.get("distribution") or {},
                "cycle_months": entry.get("cycle_months") or entry.get("cycleMonths") or base["cycle_months"],
            }
        )
    return (out or fallback_variants(kind)), escalate


def guess_kind(draft: dict[str, Any]) -> str:
    """Rough hint only. The agent drafts, the specialist confirms."""
    haystack = " ".join(
        draft_value(draft, field) for field in ("name", "intendedUse", "composition")
    ).lower()
    drug_markers = ("мг", "таблет", "капсул", "раствор для инфузий", "mg", "tablet", "capsule", "infusion")
    if any(marker in haystack for marker in drug_markers):
        return "drug"
    return "device"


# -------------------------------------------------------------- the node map --

def default_node_map(
    kind: str = "device",
    track: str = "pp1684",
    risk_class: str = "2b",
    measuring_instrument: bool = False,
) -> list[dict[str, Any]]:
    """Thirteen nodes, M0..M12.

    Everything after filing is emitted with status 'later' on purpose: the
    client should see a 12-16 month horizon from day one, not only the dossier.
    Inspection depends on the class, so M7 may be dropped.
    """
    inspection_needed = risk_class in ("2b", "3") or kind == "drug"

    nodes: list[dict[str, Any]] = [
        {
            "code": "M0",
            "title": _l10n("Классификация и процедура", "Classification and procedure", "定性与程序"),
            "owner": "us",
            "status": "done",
            "due_hint": _l10n("неделя 1", "week 1", "第 1 周"),
            "blocked_by": [],
        },
        {
            "code": "M1",
            "title": _l10n("Договор и мандат УПП", "Contract and authorized representative", "合同与授权代表"),
            "owner": "us",
            "status": "planned",
            "due_hint": _l10n("недели 2–6", "weeks 2-6", "第 2–6 周"),
            "blocked_by": ["M0"],
            "note": _l10n(
                "Доверенность закреплена за вами, смена УПП — по требованию.",
                "The power of attorney stays yours; the representative can be changed on request.",
                "委托书归您所有，可按要求更换授权代表。",
            ),
        },
        {
            "code": "M2",
            "title": _l10n("Досье собрано", "Dossier assembled", "档案齐备"),
            "owner": "us",
            "status": "planned",
            "due_hint": _l10n("месяцы 2–4", "months 2-4", "第 2–4 个月"),
            "blocked_by": ["M1"],
            "note": _l10n("Структура по п. 65 ПП 1684.", "Structure per clause 65 of Decree 1684.", "结构依第 1684 号决议第 65 条。"),
        },
        {
            "code": "M3",
            "title": _l10n("Перевод и апостиль", "Translation and apostille", "翻译与附加证明书"),
            "owner": "us",
            "status": "planned",
            "due_hint": _l10n("месяцы 2–3", "months 2-3", "第 2–3 个月"),
            "blocked_by": ["M1"],
        },
        {
            "code": "M4",
            "title": _l10n("Образцы в Россию", "Samples to Russia", "样品运抵俄罗斯"),
            "owner": "contractor",
            "status": "planned",
            "due_hint": _l10n("месяц 3", "month 3", "第 3 个月"),
            "blocked_by": ["M2"],
            "note": _l10n("Уведомление 201н и таможня.", "Notification 201n and customs.", "201н 通知与海关。"),
        },
        {
            "code": "M5",
            "title": _l10n("Испытания", "Testing", "检测"),
            "owner": "contractor",
            "status": "planned",
            "due_hint": _l10n("месяцы 4–7", "months 4-7", "第 4–7 个月"),
            "blocked_by": ["M4"],
            "note": _l10n(
                "Аккредитованная лаборатория РФ. Отчёты NMPA и CE её не заменяют.",
                "An accredited Russian laboratory. NMPA and CE reports do not replace it.",
                "俄罗斯认可实验室。NMPA 和 CE 报告不能替代。",
            ),
        },
        {
            "code": "M6",
            "title": _l10n("Клиническая оценка", "Clinical evaluation", "临床评价"),
            "owner": "contractor",
            "status": "planned",
            "due_hint": _l10n("месяцы 5–8", "months 5-8", "第 5–8 个月"),
            "blocked_by": ["M5"],
        },
    ]

    if inspection_needed:
        nodes.append(
            {
                "code": "M7",
                "title": _l10n("Инспекция производства", "Manufacturing inspection", "生产检查"),
                "owner": "gov",
                "status": "later",
                "due_hint": _l10n("месяц 8", "month 8", "第 8 个月"),
                "blocked_by": ["M6"],
                "note": _l10n("ПП РФ № 135, выезд на площадку.", "Decree No. 135, an on-site visit.", "第 135 号决议，现场检查。"),
            }
        )

    filing_blockers = ["M6"] + (["M7"] if inspection_needed else [])
    nodes.extend(
        [
            {
                "code": "M8",
                "title": _l10n("Подача и экспертиза", "Filing and review", "申报与审评"),
                "owner": "gov",
                "status": "later",
                "due_hint": _l10n("месяцы 9–13", "months 9-13", "第 9–13 个月"),
                "blocked_by": filing_blockers,
            },
            {
                "code": "M9",
                "title": _l10n("Русская маркировка", "Russian labelling", "俄文标识"),
                "owner": "us",
                "status": "later",
                "due_hint": _l10n("2 недели", "2 weeks", "2 周"),
                "blocked_by": ["M8"],
            },
            {
                "code": "M10",
                "title": _l10n("Честный ЗНАК", "Chestny Znak", "诚实标志"),
                "owner": "us",
                "status": "later",
                "due_hint": _l10n("1 неделя", "1 week", "1 周"),
                "blocked_by": ["M9"],
                "note": _l10n(
                    "Проверка по актуальной редакции перечня, а не по памяти.",
                    "Checked against the current list, not from memory.",
                    "按现行清单核对，而非凭记忆。",
                ),
            },
            {
                "code": "M11",
                "title": _l10n("Мониторинг безопасности", "Safety monitoring", "安全监测"),
                "owner": "us",
                "status": "later",
                "due_hint": _l10n("2 недели", "2 weeks", "2 周"),
                "blocked_by": ["M8"],
                "note": _l10n("Приказ № 1113н.", "Order No. 1113n.", "第 1113н 号令。"),
            },
            {
                "code": "M12",
                "title": _l10n("Первая легальная продажа", "First legal sale", "首次合法销售"),
                "owner": "you",
                "status": "goal",
                "due_hint": _l10n("месяцы 13–14", "months 13-14", "第 13–14 个月"),
                "blocked_by": ["M9", "M10", "M11"],
                "note": _l10n(
                    "Метрика успеха, отдельная от выдачи удостоверения.",
                    "The success metric, separate from the authorization being issued.",
                    "成功指标，与注册证签发相区分。",
                ),
            },
        ]
    )

    if measuring_instrument:
        for node in nodes:
            if node["code"] == "M5":
                node["note"] = _l10n(
                    "Плюс утверждение типа средства измерений по приказу № 257н.",
                    "Plus measuring instrument type approval under order No. 257n.",
                    "另需按第 257н 号令进行计量器具型式批准。",
                )

    for position, node in enumerate(nodes):
        node["position"] = position
    return nodes


def critical_node(nodes: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """The one next action. The map and the task list must not disagree."""
    for node in nodes:
        if node.get("status") == "in_progress":
            return node
    for node in nodes:
        if node.get("status") == "planned":
            return node
    return None

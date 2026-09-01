-- Demo orgs so POST /cases does not invent a legal entity (design §2).

UPSERT INTO organizations (organization_id, kind, name_json, created_at)
VALUES
    (
        "org-cn-demo",
        "cn",
        '{"ru":"Производитель (демо КНР)","en":"Demo CN manufacturer","zh":"演示中国厂家"}',
        CurrentUtcTimestamp()
    ),
    (
        "org-rf-upp",
        "rf-upp",
        '{"ru":"УПП (демо РФ)","en":"Demo RF authorized representative","zh":"演示俄方授权代表"}',
        CurrentUtcTimestamp()
    );

# Multi-Tenant Adim 10 Sirket Bazli Numara Migration Notu

Bu adimda numara ve kategori benzersizlikleri firma bazli hale getirildi.

## Degisen Benzersizlik Kurallari

- `actions`: `action_number` yerine `(company_id, action_number)`
- `dofs`: `dof_no` yerine `(company_id, dof_no)`
- `internal_audits`: `audit_no` yerine `(company_id, audit_no)`
- `maintenance_faults`: `fault_number` yerine `(company_id, fault_number)`
- `maintenance_machines`: `code` yerine `(company_id, code)`
- `document_categories`: `slug` yerine `(company_id, slug)`
- `quality_test_records`: `(company_id, test_type, record_number)`

## Sayac Davranisi

Sayaç keyleri firma bazli tutulur:

```text
company:{company_id}:next_action_number
company:{company_id}:next_dof_number_2026
company:{company_id}:next_internal_audit_number_2026
company:{company_id}:next_maintenance_fault_number
```

Firma baglami yoksa eski global key davranisi korunur.

## Canliya Almadan Once

Mutlaka yedek alin:

```bash
cp /var/data/aksiyon-takip/actions.db /var/data/aksiyon-takip/actions-before-step10.db
```

Migration:

```bash
cd /var/www/aksiyon-takip
sudo -u aksiyon ./venv/bin/python -m flask --app app:create_app db upgrade
sudo -u aksiyon ./venv/bin/python -m pytest tests/test_tenant.py
sudo systemctl restart aksiyon-takip
```

## Dogrulama

- Er Prefabrik icin yeni aksiyon ac.
- Yeni firma icin yeni aksiyon ac.
- Yeni firmada numaranin kendi sirasi ile ilerledigini kontrol et.
- Yeni firmada dokuman kategorilerinin kendi firma kapsamina olustugunu kontrol et.

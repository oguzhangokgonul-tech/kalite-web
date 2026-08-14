# Multi-Tenant Adim 9 Sirket Bazli Sayac ve Numara Plani

Bu adimda kod davranisi degistirilmeden numara uretimi ve global unique riskleri
incelendi. Amac sonraki migration adimini canli veriyi bozmadan planlamaktir.

## Mevcut Durum

| Alan | Mevcut tablo/kolon | Mevcut davranis | Risk |
| --- | --- | --- | --- |
| Aksiyon no | `actions.action_number` | `next_action_number` AppSetting key'i global ilerler | Yeni firmalar `#1`den baslayamaz |
| IF no | `dofs.dof_no` | `next_dof_number_{year}` global ilerler | `IF-2026-0001` sadece bir firmada kullanilabilir |
| Ic denetim no | `internal_audits.audit_no` | `next_internal_audit_number_{year}` global ilerler | `ICD-2026-0001` sadece bir firmada kullanilabilir |
| Bakim ariza no | `maintenance_faults.fault_number` | `next_maintenance_fault_number` global ilerler | Yeni firmalar BAK numarasinda global sirayi takip eder |
| Kalite deney no | `quality_test_records.record_number` | Test tipine gore global maksimum + 1 | Ayni test tipinde firmalar ortak siradan devam eder |
| Dokuman kategori slug | `document_categories.slug` | Global unique | Yeni firmada ayni kategori slug'i tekrar acilamaz |
| App ayarlari | `app_settings.key` | Sadece `key` primary key | Firma bazli ayar/sayac ayni key ile tutulamaz |

## Mevcut Kod Noktalari

- `reserve_action_number()`
- `reserve_dof_number(today=None)`
- `reserve_internal_audit_number(today=None)`
- `reserve_maintenance_fault_number()`
- `reserve_quality_test_record_number(slug)`
- `initialize_document_categories()`
- `AppSetting`

## Onerilen Hedef Davranis

Yeni firma bos basladiginda kendi numara dizisini kullanmali:

- Er Prefabrik: `#1`, `IF-2026-0001`, `ICD-2026-0001`
- Yeni Firma: `#1`, `IF-2026-0001`, `ICD-2026-0001`

Bu ancak unique constraint ve sayac yapisi firma bazli hale gelirse guvenlidir.

## Gerekli Migration Degisiklikleri

### 1. Unique constraint/index degisiklikleri

SQLite uzerinde mevcut global unique constraintler dogrudan alter edilemez. Bu
nedenle Alembic `batch_alter_table(..., recreate="always")` mantigi kullanilmali.

Onerilen yeni unique yapilar:

- `actions`: `(company_id, action_number)`
- `dofs`: `(company_id, dof_no)`
- `internal_audits`: `(company_id, audit_no)`
- `maintenance_faults`: `(company_id, fault_number)`
- `document_categories`: `(company_id, slug)`
- `maintenance_machines`: `(company_id, code)` degerlendirilmeli

### 2. AppSetting firma bazli hale getirilmeli

Mevcut model:

```text
key primary key
value
```

Onerilen model:

```text
id primary key
company_id nullable index
key
value
unique(company_id, key)
```

Alternatif kisa vadeli cozum:

```text
key = company:{company_id}:next_action_number
```

Bu kisa vadeli cozum tablo migrationini azaltir ama uzun vadede temiz degildir.

## Geriye Donuk Veri Tasima

Mevcut tum kayitlar Er Prefabrik firmasina (`001`) bagli oldugu icin:

- Mevcut numaralar korunur.
- Mevcut global AppSetting keyleri Er Prefabrik icin yeni firma bazli keylere
  kopyalanir.
- Superadmin/global ayarlar varsa `company_id = NULL` ile ortak ayar olarak
  tutulur.

## Kod Degisikligi Sirasi

1. Migration ile unique constraintler firma bazli hale getirilir.
2. `AppSetting` firma bazli modele gecirilir veya gecici olarak firma prefixli
   key yardimcisi eklenir.
3. `reserve_*` fonksiyonlari `current_company_id()` kapsamina gore sayac okur.
4. Maksimum numara sorgulari `company_id == current_company_id()` ile filtrelenir.
5. Yeni firma icin numara uretim testleri eklenir.
6. Canliya almadan once staging/yerelde mevcut DB kopyasiyla migration denenir.

## Mutlaka Eklenmesi Gereken Testler

- Er Prefabrik ve Deneme firmasi icin ayni `action_number=1` uretilebilir.
- Er Prefabrik ve Deneme firmasi icin ayni `IF-2026-0001` uretilebilir.
- Er Prefabrik ve Deneme firmasi icin ayni `ICD-2026-0001` uretilebilir.
- Ayni firma icinde ayni numara ikinci kez uretilemez.
- Eski global AppSetting keyleri migration sonrasi kaybolmaz.
- Dokuman kategorileri iki firmada ayni slug ile olusturulabilir.

## Riskler

- SQLite tablo yeniden olusturma sirasinda foreign key iliskileri dikkatli
  yonetilmeli.
- Eski bozuk/NULL `company_id` kayitlari varsa migration oncesi raporlanmali.
- Canli migration once veritabani yedegi alinmadan calistirilmamali.
- Global unique constraint kaldirilmadan `reserve_*` fonksiyonlari firma bazli
  yapilirsa kayit olusturma hatalari olusur.

## Sonuc

Adim 9 icin en dogru karar: once migration planini netlestirmek, sonra Adim 10'da
unique constraint ve `AppSetting` yapisini kontrollu sekilde donusturmektir.
Bu adimda canli davranis degistirilmedi.

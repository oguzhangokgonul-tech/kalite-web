# Multi-Tenant Adim 13 Yeni Firma Acilis Otomasyonu

Bu adim yeni firma acilisinda teknik baslangic ayarlarini otomatik hale getirir.

## Ne Otomatiklesir?

Yeni firma olusturulunca su AppSetting sayaclari firma bazli olarak hazirlanir:

```text
company:{company_id}:next_action_number
company:{company_id}:next_dof_number_{year}
company:{company_id}:next_internal_audit_number_{year}
company:{company_id}:next_maintenance_fault_number
```

Bu sayede yeni firma:

- Ilk aksiyonda `#1`den baslar.
- Ilk IF kaydinda kendi `IF-YYYY-0001` numarasini alir.
- Ilk ic denetimde kendi `ICD-YYYY-0001` numarasini alir.
- Ilk bakim arizasinda kendi bakim numarasini alir.

Mevcut Er Prefabrik verileri yeni firmaya kopyalanmaz.

## Yeni CLI Komutu

Firma daha once olusturulduysa veya kontrol amacli tekrar calistirmak istersen:

```bash
sudo -u aksiyon ./venv/bin/python -m flask --app app:create_app company-bootstrap 002
```

`002` yerine ilgili firma kodu yazilir.

Komut tekrar tekrar calistirilabilir. Mevcut ayarlari bozmaz, sadece eksik olanlari tamamlar.

## Tenant Health Entegrasyonu

`tenant-health` artik aktif firmalar icin baslangic sayaclarini da kontrol eder.

- Eksik sayac varsa `WARN` verir.
- `WARN` siteyi durdurmaz.
- Eksik sayaclari tamamlamak icin `company-bootstrap` calistirilabilir.

## Canli Sunucu Uygulama

```bash
cd /var/www/aksiyon-takip
git pull origin main
sudo -u aksiyon ./venv/bin/python -m flask --app app:create_app db upgrade
sudo -u aksiyon ./venv/bin/python -m flask --app app:create_app tenant-health
sudo systemctl restart aksiyon-takip
```

Eger `tenant-health` herhangi bir firma icin baslangic sayaci uyarisi verirse:

```bash
sudo -u aksiyon ./venv/bin/python -m flask --app app:create_app company-bootstrap 001
sudo -u aksiyon ./venv/bin/python -m flask --app app:create_app company-bootstrap 000
sudo -u aksiyon ./venv/bin/python -m flask --app app:create_app tenant-health
sudo systemctl restart aksiyon-takip
```

## Manuel Kontrol Senaryosu

1. `superadmin` ile `volkaportal.com` uzerinden giris yap.
2. `Sirket Yonetimi` sayfasindan yeni firma olustur.
3. Yeni firma domain/subdomain ayarini kontrol et.
4. Firma secimiyle yeni firmaya gec.
5. Yeni firmada ilk kullaniciyi olustur.
6. Yeni firma subdomaininden bu kullanici ile giris yap.
7. Ilk aksiyon, IF veya ic denetim numarasinin `0001`den basladigini kontrol et.

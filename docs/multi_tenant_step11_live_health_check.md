# Multi-Tenant Adim 11 Canli Migration ve Saglik Kontrolu

Bu adim canli sunucuda migration uygulamasini kontrollu yapmak icin eklendi.
Yeni komut:

```bash
sudo -u aksiyon ./venv/bin/python -m flask --app app:create_app tenant-health
```

Komut su kontrolleri yapar:

- Beklenen temel tablolar var mi?
- `alembic_version` head degeri `202608130005` mu?
- Tenant kapsamli tablolarda `company_id` kolonu var mi?
- Sirket bazli unique yapilar dogrulanabiliyor mu?
- `001` Er Prefabrik ve `000` Deneme Hesabi mevcut mu?
- `superadmin` global hesap olarak `company_id = NULL` durumda mi?
- Aktif firmalarda `primary_domain` dolu mu?
- Kritik kayitlarda bos `company_id` var mi?

`FAIL` varsa siteyi yayina almadan once duzeltilmelidir.
`WARN` varsa sistem acilabilir, ancak not alip sonraki adimda temizlenmelidir.

## Canli Sunucuda Uygulama Sirasi

```bash
cd /var/www/aksiyon-takip
cp /var/data/aksiyon-takip/actions.db /var/data/aksiyon-takip/actions-before-step11-$(date +%Y%m%d-%H%M%S).db
git pull origin main
sudo systemctl stop aksiyon-takip
sudo -u aksiyon ./venv/bin/python -m flask --app app:create_app db upgrade
sudo -u aksiyon ./venv/bin/python -m flask --app app:create_app tenant-health
sudo -u aksiyon ./venv/bin/python -m pytest tests/test_tenant.py
sudo systemctl start aksiyon-takip
sudo systemctl status aksiyon-takip --no-pager
```

## Site Kontrolu

```bash
curl -I https://volkaportal.com
curl -I https://erprefabrik.volkaportal.com
```

Beklenen:

- `HTTP/2 200`, `HTTP/1.1 200` veya login yonlendirmesi icin `302`
- `502 Bad Gateway` olmamali
- `tenant-health` komutunda `FAIL` olmamali

## Geri Donus Plani

Migration veya saglik kontrolu basarisiz olursa:

```bash
sudo systemctl stop aksiyon-takip
cp /var/data/aksiyon-takip/actions-before-step11-YYYYMMDD-HHMMSS.db /var/data/aksiyon-takip/actions.db
sudo systemctl start aksiyon-takip
sudo systemctl status aksiyon-takip --no-pager
```

`YYYYMMDD-HHMMSS` yerine aldiginiz yedek dosyanin gercek tarih/saat ekini yazin.

## Notlar

- SQLite kullanildigi icin migration sirasinda uygulamayi durdurmak daha guvenlidir.
- Nginx acik kalabilir; uygulama durdugu kisa surede gecici 502 gorulebilir.
- `tenant-health` komutu kod tarafindaki en son beklenen migration head ile karsilastirma yapar.

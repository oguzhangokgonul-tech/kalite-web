# Multi-Tenant Adim 11 Canli Migration ve Saglik Kontrolu

Bu adim canli sunucuda migration uygulamasini kontrollu yapmak icin eklendi.
Yeni komut:

```bash
sudo -u aksiyon ./venv-py312/bin/python -m flask --app app:create_app tenant-health
```

Komut su kontrolleri yapar:

- Beklenen temel tablolar var mi?
- `alembic_version` değeri repodaki güncel Alembic head ile aynı mı?
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
sudo systemctl stop aksiyon-takip
sudo -u aksiyon ./venv-py312/bin/python -m flask --app app:create_app full-backup
sudo -u aksiyon ./venv-py312/bin/python -m flask --app app:create_app backup-verify /path/to/verified-backup.zip
sudo -u aksiyon git pull --ff-only origin main
sudo -u aksiyon ./venv-py312/bin/python -m flask --app app:create_app db upgrade
sudo -u aksiyon ./venv-py312/bin/python -m flask --app app:create_app tenant-health
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

Migration veya saglik kontrolu basarisizsa servisi durmus tutun. Dogrulanmis
tam yedek ve eslesen kod/config geri donusu icin BACKUP_RESTORE.md kullanin;
canli restore Lider onayi gerektirir. Calisan SQLite dosyasini cp ile
kopyalamayin. CLI ortaminda servisle ayni DB/upload ve SECRET_KEY ayarlarini
koruyun; ornek komutlardaki yedek yolunu gercek paketle degistirin.

## Notlar

- SQLite kullanildigi icin migration sirasinda uygulamayi durdurmak daha guvenlidir.
- Nginx acik kalabilir; uygulama durdugu kisa surede gecici 502 gorulebilir.
- `tenant-health` komutu kod tarafindaki en son beklenen migration head ile karsilastirma yapar.

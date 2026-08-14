# Multi-Tenant Adim 12 Firma Bazli Kullanici Adlari

Bu adimda kullanici adi benzersizligi global olmaktan cikarilip firma bazli hale getirildi.

## Neden Gerekli?

Login artik firma kodu ile degil subdomain ile calisir:

- `erprefabrik.volkaportal.com`
- `ornekfirma.volkaportal.com`

Bu yapida farkli firmalarda ayni kullanici adinin kullanilabilmesi gerekir.
Ornek:

- Er Prefabrik icinde `oguzhan`
- Ornek Firma icinde `oguzhan`

Bu iki hesap birbirinden farkli firmalara bagli oldugu icin artik birlikte var olabilir.

## Degisen Kural

Eski:

```text
users.username global unique
```

Yeni:

```text
unique(company_id, username)
```

Global hesaplar icin:

```text
company_id IS NULL olan username tekil kalir
```

Bu nedenle `superadmin` ortak/global hesap olarak tek kalmaya devam eder.

## Login Davranisi

- Firma subdomaininden gelen login isteginde once o firmanin kullanicisi aranir.
- Superadmin gibi global hesaplar yine bulunabilir.
- Ana domainde firma kullanicilariyla giris yapilmaz; firma subdomaini gerekir.

## Canli Sunucu Uygulama

```bash
cd /var/www/aksiyon-takip
cp /var/data/aksiyon-takip/actions.db /var/data/aksiyon-takip/actions-before-step12-$(date +%Y%m%d-%H%M%S).db
git pull origin main
sudo systemctl stop aksiyon-takip
sudo -u aksiyon ./venv/bin/python -m flask --app app:create_app db upgrade
sudo -u aksiyon ./venv/bin/python -m flask --app app:create_app tenant-health
sudo -u aksiyon ./venv/bin/python -m pytest tests/test_tenant.py
sudo systemctl start aksiyon-takip
sudo systemctl status aksiyon-takip --no-pager
```

## Manuel Kontrol Senaryosu

1. `superadmin` ile `volkaportal.com` adresinden giris yap.
2. Yeni firma olustur veya mevcut deneme firmasina gec.
3. Yeni firmada Er Prefabrik'te var olan bir kullanici adiyla test kullanicisi ac.
4. Yeni firmanin subdomaininden bu kullanici ile giris yap.
5. Er Prefabrik subdomaininden ayni kullanici adi ile Er Prefabrik kullanicisinin acildigini kontrol et.

## Geri Donus

Migration basarisiz olursa:

```bash
sudo systemctl stop aksiyon-takip
cp /var/data/aksiyon-takip/actions-before-step12-YYYYMMDD-HHMMSS.db /var/data/aksiyon-takip/actions.db
sudo systemctl start aksiyon-takip
```

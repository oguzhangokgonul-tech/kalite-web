# Multi-Tenant Guvenlik Kontrol Listesi

Bu kontrol listesi yeni firma acildiktan veya tenant/domain kodu degistirildikten sonra calistirilir.

## Otomatik Test

Yerel ortamda:

```bash
python -m pytest tests/test_tenant.py
```

Sunucuda venv ile:

```bash
cd /var/www/aksiyon-takip
sudo -u aksiyon ./venv/bin/python -m pytest tests/test_tenant.py
```

Beklenen sonuc:

```text
8 passed
```

## Canli Ortam Manuel Testi

### 1. Domain Sirket Eslesmesi

```bash
curl -I https://erprefabrik.volkaportal.com
```

Beklenen:

- HTTPS hatasi yok
- `erprefabrik.volkaportal.com` ana domaine yonlenmiyor
- Login ekrani sirket kodu istemiyor

### 2. Er Prefabrik Kullanici Girisi

Adres:

```text
https://erprefabrik.volkaportal.com
```

Er Prefabrik kullanicisi ile giris yap.

Kontrol:

- Ana sayfa aciliyor
- Sadece Er Prefabrik kayitlari gorunuyor
- Sirket kodu sorulmuyor

### 3. Yanlis Firma Kullanici Girisi

Er Prefabrik subdomaininde baska firmaya ait kullanici ile giris denenir.

Beklenen:

- Giris reddedilir
- Kullanici diger firmaya ait verileri goremez

### 4. Super Admin Ortak Giris

Adres:

```text
https://volkaportal.com
```

`superadmin` ile giris yap.

Kontrol:

- Sirket Yonetimi gorunuyor
- Sirketler arasi gecis calisiyor
- Secilen sirketin verileri geliyor

### 5. Liste Izolasyonu

Her firma icin kontrol edilmesi gereken sayfalar:

- Ana Sayfa / Aksiyonlar
- Gorevlerim
- IF Yonetimi
- Ic Denetim Yonetimi
- Dokuman Yonetimi
- Bakim
- Kalite Deneyleri
- Bildirimler

Beklenen:

- Normal kullanici sadece kendi firmasina ait kayitlari gorur
- Super Admin firma seciliyse sadece secili firma kayitlarini gorur
- Super Admin ortak gorunumde tum firmalari yonetebilir

### 6. Detay Route Izolasyonu

Bir firmaya ait kaydin detay URL'si diger firma kullanicisiyla acilmaya calisilir.

Beklenen:

- 404 veya 403 doner
- Karsilikli veri sizintisi olmaz

### 7. Dosya Indirme Izolasyonu

Dokuman, aksiyon kaniti, IF kaniti ve diger upload dosyalari icin indirme linkleri test edilir.

Beklenen:

- Kendi firmasina ait dosyalar iner
- Baska firmaya ait dosya linki 404 veya 403 verir

## Risk Notlari

- Yeni firma acarken DNS/Nginx/SSL adimlari eksik kalirsa domain sirket secimi calismaz.
- Wildcard DNS/SSL yapisina gecilene kadar her subdomain teknik olarak ayrica eklenmelidir.
- Yeni tablo veya yeni modül eklendiginde mutlaka `company_id` ve `scoped_query` kullanimi kontrol edilmelidir.

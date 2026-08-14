# Multi-Tenant Adim 16 Son Guvenlik ve Satisa Hazirlik Kontrolu

Bu dokuman VolkaPortal'i yeni firma/tenant yapisi ile demo veya satis gorusmesine cikarmadan once uygulanacak son kontrol listesidir.

## 1. Teknik Kabul

Sunucuda:

```bash
cd /var/www/aksiyon-takip
git pull origin main
sudo -u aksiyon ./venv/bin/python -m flask --app app:create_app db upgrade
sudo -u aksiyon ./venv/bin/python -m flask --app app:create_app seed-users
sudo -u aksiyon ./venv/bin/python -m flask --app app:create_app tenant-health
sudo -u aksiyon ./venv/bin/python -m pytest tests/test_tenant.py
sudo systemctl restart aksiyon-takip
```

Kabul:

- `tenant-health` ciktisinda `FAIL` yok.
- Test sonucu `21 passed`.
- `systemctl status aksiyon-takip` active running.
- `systemctl status nginx` active running.

## 2. Domain / SSL Kabul

Kontrol:

```bash
curl -I https://volkaportal.com
curl -I https://erprefabrik.volkaportal.com
```

Kabul:

- SSL uyari yok.
- `502 Bad Gateway` yok.
- `erprefabrik.volkaportal.com` ana domaine zorla yonlenmiyor.
- Login ekrani sirket kodu istemiyor.

Yeni firma test edilecekse:

```bash
nslookup ornekfirma.volkaportal.com
curl -I https://ornekfirma.volkaportal.com
```

## 3. Superadmin Kabul

Adres:

```text
https://volkaportal.com/login
```

Kabul:

- `superadmin` giris yapabiliyor.
- `Sirket Yonetimi` sayfasini gorebiliyor.
- Firma listesinde `Hazirlik` kolonu var.
- Aktif firmalarda `Hazir` gorunuyor.
- Firma secimi ile Er Prefabrik / Deneme / yeni firma arasinda gecis yapabiliyor.

## 4. Firma Izolasyonu Kabul

Her firma icin su sayfalar kontrol edilir:

- Ana Sayfa
- Gorevlerim
- Kullanicilar
- IF Yonetimi
- Ic Denetim Yonetimi
- Dokuman Yonetimi
- Bakim
- Kalite Deneyleri
- Bildirimler

Kabul:

- Normal kullanici yalnizca kendi firmasinin verisini gorur.
- Diger firmaya ait detay linki 404 veya 403 verir.
- Superadmin firma seciliyse secili firma verisini gorur.
- Superadmin ortak gorunumde sistem yonetimi yapabilir.

## 5. Dosya Guvenligi Kabul

Kontrol edilecek moduller:

- Aksiyon dosyalari
- Aksiyon kapanis kanitlari
- IF dosyalari
- Dokuman dosyalari
- Ic denetim ciktilari

Kabul:

- Yeni yuklenen dosyalar `uploads/company-XXX/...` altinda saklanir.
- Kendi firmasina ait dosya indirilebilir.
- Baska firmaya ait dosya linki kullaniciya acilmaz.
- Eski legacy dosyalar calisiyorsa sadece yetkili kayit uzerinden erisilir.

## 6. Yeni Firma Demo Senaryosu

1. Superadmin ile giris yap.
2. `Sirket Yonetimi > Yeni Sirket Ekle` ekranindan `002 - Ornek Firma` ac.
3. Firma listesinde `Hazir` ve sayaclar `0` gor.
4. Ana sayfada firma seciminden `002 - Ornek Firma` sec.
5. Yeni kullanici olustur.
6. Yeni kullanici ile `ornekfirma.volkaportal.com` uzerinden giris yap.
7. Ilk aksiyonun `#1` ile basladigini kontrol et.
8. Er Prefabrik verilerinin gorunmedigini kontrol et.

## 7. Yedek ve Geri Donus

Deployment oncesi:

```bash
cp /var/data/aksiyon-takip/actions.db /var/data/aksiyon-takip/actions-before-release-$(date +%Y%m%d-%H%M%S).db
```

Geri donus:

```bash
sudo systemctl stop aksiyon-takip
cp /var/data/aksiyon-takip/actions-before-release-YYYYMMDD-HHMMSS.db /var/data/aksiyon-takip/actions.db
sudo systemctl start aksiyon-takip
```

## 8. Satis / Demo Hazirlik

Demo oncesi hazirlanacaklar:

- Demo firma: `demo.volkaportal.com` veya `deneme.volkaportal.com`
- Demo kullanicilari ve roller
- Ornek aksiyon kayitlari
- Ornek IF akisi
- Ornek ic denetim ciktilari
- Ornek dokuman kategorileri
- Ornek bakim ariza kaydi
- Ornek kalite deney kaydi

Demo anlatim basliklari:

- Tek sistem, cok firma
- Firma bazli veri izolasyonu
- Rol ve yetki yonetimi
- Aksiyon / IF / ic denetim / dokuman / bakim / kalite deneyleri tek portalda
- Bildirim ve e-posta altyapisi
- Subdomain ile firma girisi

## 9. Kalan Urunlestirme Notlari

Teknik tenant gecisi tamamlandiktan sonra urunlestirme icin onerilen siralama:

1. Demo veri seti hazirla.
2. Paket ve fiyatlandirma tablosu hazirla.
3. Musteri onboarding dokumani hazirla.
4. Kullanici egitim PDF'i hazirla.
5. Yedekleme otomasyonu ekle.
6. Hata izleme/log izleme standardi ekle.

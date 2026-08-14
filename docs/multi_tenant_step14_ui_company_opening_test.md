# Multi-Tenant Adim 14 UI Uzerinden Yeni Firma Acilis Testi

Bu adim kod degisikliginden cok canli sistem davranisini dogrulama adimidir.

## Amac

Superadmin ile yeni firma acildiginda:

- Firma kaydi olussun.
- Baslangic sayaclari hazir olsun.
- Yeni firma bos baslasin.
- Er Prefabrik verileri yeni firmada gorunmesin.
- Yeni firmaya ilk kullanici atanabilsin.
- Ayni kullanici adi farkli firmalarda cakismasin.

## On Kosul

Sunucuda son kod alinmis olmali:

```bash
cd /var/www/aksiyon-takip
git pull origin main
sudo -u aksiyon ./venv/bin/python -m flask --app app:create_app db upgrade
sudo -u aksiyon ./venv/bin/python -m flask --app app:create_app seed-users
sudo -u aksiyon ./venv/bin/python -m flask --app app:create_app tenant-health
sudo systemctl restart aksiyon-takip
```

`tenant-health` ciktisinda `FAIL` olmamali.

## UI Test Senaryosu

### 1. Superadmin Girisi

1. `https://volkaportal.com/login` adresine gir.
2. `superadmin` kullanicisi ile giris yap.
3. Sol menude `Sirket Yonetimi` sayfasini ac.

Beklenen:

- Sayfa sadece superadmin tarafindan gorulur.
- Mevcut firmalar listelenir.
- Her firmada `Hazirlik` kolonu gorunur.

### 2. Yeni Firma Kaydi

1. `Yeni Sirket Ekle` butonuna bas.
2. Ornek degerlerle firma ac:

```text
Sirket Kodu: 002
Sirket Adi: Ornek Firma
Sirket Adres Adi: ornekfirma
Ana Domain: ornekfirma.volkaportal.com
Aktif sirket: secili
```

3. `Sirketi Kaydet` butonuna bas.

Beklenen:

- Firma listesine geri doner.
- `002 - Ornek Firma` gorunur.
- `Hazirlik` kolonu `Hazir` gorunur.
- Kullanici, Aksiyon, IF, Ic Denetim, Dokuman sayilari `0` gorunur.

### 3. Firma Secimi

1. Ana sayfaya git.
2. Superadmin firma seciminden `002 - Ornek Firma` sec.

Beklenen:

- Ana sayfa bos/temiz gorunur.
- Er Prefabrik aksiyonlari burada gorunmez.
- Yeni aksiyon acilirsa numara `#1`den baslar.

### 4. Ilk Kullanici Olusturma

1. `Kullanicilar` sayfasina gir.
2. Yeni firma seciliyken test kullanicisi olustur:

```text
Kullanici adi: oguzhan
Ad Soyad: Ornek Firma Oguzhan
Gorev: Test Kullanici
Sifre: test1234
```

3. Gerekli rol/yetkileri ata.

Beklenen:

- Er Prefabrik icindeki `oguzhan` kullanicisiyle cakisma olmaz.
- Yeni kullanici `002 - Ornek Firma` altinda olusur.

### 5. Subdomain Giris Testi

DNS/SSL hazirsa:

1. `https://ornekfirma.volkaportal.com/login` adresine git.
2. Yeni olusturulan test kullanicisi ile giris yap.

Beklenen:

- Kullanici sadece Ornek Firma verilerini gorur.
- Er Prefabrik verileri gorunmez.
- Ana domainden firma kullanicisiyle giris yapmaya calisildiginda uyari alinir.

### 6. Temizlik

Test firmasi kalici kullanilmayacaksa:

- Firmayi pasife al.
- Test kullanicisini pasife al.
- DNS/SSL kaydi acilmadiysa herhangi bir ek temizlik gerekmez.

## Teknik Kontrol Komutlari

Yeni firma kodu icin baslangic ayarlarini tekrar kontrol/onar:

```bash
sudo -u aksiyon ./venv/bin/python -m flask --app app:create_app company-bootstrap 002
sudo -u aksiyon ./venv/bin/python -m flask --app app:create_app tenant-health
```

## Basarili Kabul Kriteri

- `tenant-health` ciktisinda `FAIL` yok.
- Yeni firma listede `Hazir` gorunuyor.
- Yeni firma veri sayilari baslangicta `0`.
- Ayni kullanici adi farkli firmalarda kullanilabiliyor.
- Yeni firma subdomaininden giren kullanici baska firmanin verisini gormuyor.

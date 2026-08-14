# Yeni Firma Acma Standardi

Bu dokuman VolkaPortal icinde yeni bir firma/tenant acarken izlenecek standart sirayi tanimlar.

## 1. Sirket Kaydini Olustur

Super Admin olarak `Sirket Yonetimi > Yeni Sirket Ekle` ekranina girilir.

Zorunlu alanlar:

- Sirket Kodu: `002`, `003` gibi 3 haneli benzersiz kod
- Sirket Adi

Onerilen alanlar:

- Sirket Adres Adi: `ornekfirma`
- Ana Domain: bos birakilirsa sistem `ornekfirma.{TENANT_BASE_DOMAIN}` olarak uretir
- Ozel Domain: sadece musteri kendi domainini kullanacaksa doldurulur

Yeni firma bos veriyle baslar. Mevcut Er Prefabrik verileri yeni firmaya kopyalanmaz.

## 2. DNS Kaydi Ekle

Tercih edilen yapi wildcard DNS kaydidir. Bu kayit bir kez eklenirse
`erprefabrik.volkaportal.com`, `ornekfirma.volkaportal.com` gibi yeni
subdomainler ayrica DNS kaydi istemeden ayni sunucuya gider.

Onerilen:

```text
Type: A
Host: *
Value: 94.103.45.122
TTL: 30 dk veya 1 saat
```

Wildcard kullanilmiyorsa tekil subdomain kaydi eklenir:

```text
Type: A
Host: ornekfirma
Value: 94.103.45.122
TTL: 30 dk veya 1 saat
```

Kontrol:

```bash
nslookup ornekfirma.volkaportal.com
```

Beklenen IP:

```text
94.103.45.122
```

## 3. Nginx Ayarini Guncelle

Onerilen Nginx yapisi wildcard `server_name` kullanir.

Ornek:

```nginx
server_name volkaportal.com www.volkaportal.com *.volkaportal.com;
```

Kontrol:

```bash
nginx -t
systemctl reload nginx
```

## 4. SSL Sertifikasina Ekle

Uzun vadeli onerilen yapi wildcard SSL sertifikasidir.

```bash
certbot certonly --manual --preferred-challenges dns -d volkaportal.com -d "*.volkaportal.com"
```

Wildcard SSL kullanilmiyorsa yeni subdomain mevcut sertifikaya tekil olarak eklenir.

```bash
certbot --nginx -d volkaportal.com -d www.volkaportal.com -d erprefabrik.volkaportal.com -d ornekfirma.volkaportal.com
```

## 5. Ilk Kullanicilari Olustur

Super Admin ilgili firmaya gecer ve o firmaya ait ilk kullanicilari olusturur.

Kontrol edilmesi gerekenler:

- Kullanici `company_id` yeni firmaya bagli mi?
- Roller dogru mu?
- Kullanici yeni subdomain uzerinden giris yapabiliyor mu?

## 6. Fonksiyon Kontrolu

Yeni firma icin temel kontrol listesi:

- Ana sayfa bos veya sadece o firmaya ait veriyle aciliyor
- Aksiyon olusturma/listeleme calisiyor
- IF kayitlari sadece o firmaya ait gorunuyor
- Ic denetim kayitlari sadece o firmaya ait gorunuyor
- Dokumanlar sadece o firmaya ait gorunuyor
- Bildirimler sadece o firmaya ait gorunuyor
- Dosya yukleme/indirme yetkileri dogru calisiyor

## 7. Notlar

- Sirket kodu artik giris ekrani icin kullanilmaz; sistem firmayi domain/subdomain uzerinden secer.
- Sirket kodu sadece envanter ve idari takip amaciyla tutulur.
- Canli ortamda oturumun ana domain ve subdomainler arasinda korunmasi icin `SESSION_COOKIE_DOMAIN=.volkaportal.com` mantigi kullanilir.
- Uzun vadede wildcard DNS, wildcard Nginx ve wildcard SSL yapisina gecilirse 2-4. adimlar otomatiklesebilir.

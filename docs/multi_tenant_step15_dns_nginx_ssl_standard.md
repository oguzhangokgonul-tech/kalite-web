# Multi-Tenant Adim 15 DNS / Nginx / SSL Yeni Firma Standardi

Bu adim yeni firma subdomainlerini surdurulebilir sekilde yayina almak icin standart operasyon planidir.

## Hedef Yapi

Tek uygulama, firma subdomainlerine gore tenant secer:

```text
volkaportal.com                 -> ortak / superadmin girisi
erprefabrik.volkaportal.com     -> 001 Er Prefabrik
ornekfirma.volkaportal.com      -> 002 Ornek Firma
*.volkaportal.com               -> aktif firmalar
```

Uygulama tarafinda firma secimi `Host` header uzerinden yapilir.
Bu nedenle DNS, Nginx ve SSL ayni host adlarini desteklemelidir.

## 1. DNS Standardi

Onerilen yapi wildcard DNS kaydidir. Bu kayit bir kez eklendikten sonra yeni firma icin tekrar DNS kaydi eklemek gerekmez.

Spaceship DNS ekraninda:

```text
Type / Tur: A
Host / Ana Bilgisayar: *
Value / Deger: 94.103.45.122
TTL: 30 dk veya 1 saat
```

Kok domain icin de A kaydi olmalidir:

```text
Type / Tur: A
Host / Ana Bilgisayar: @
Value / Deger: 94.103.45.122
TTL: 30 dk veya 1 saat
```

`www` icin:

```text
Type / Tur: CNAME
Host / Ana Bilgisayar: www
Value / Deger: volkaportal.com
TTL: 30 dk veya 1 saat
```

Kontrol:

```bash
nslookup volkaportal.com
nslookup erprefabrik.volkaportal.com
nslookup ornekfirma.volkaportal.com
```

Beklenen IP:

```text
94.103.45.122
```

## 2. Nginx Standardi

Tek bir Nginx site dosyasi kullanilmalidir.

Ornek dosya projeye eklendi:

```text
deploy/nginx/volkaportal.conf.example
```

Canli sunucuda uygulanacak temel mantik:

```nginx
server_name volkaportal.com www.volkaportal.com *.volkaportal.com;
proxy_pass http://127.0.0.1:8000;
proxy_set_header Host $host;
```

`Host $host` satiri kritiktir. Uygulama hangi firmaya girildigini bu bilgiyle anlar.

Canli sunucuda kontrol:

```bash
ls -lah /etc/nginx/sites-enabled
nginx -T | grep -n "server_name"
nginx -t
```

Eger ayni domain birden fazla Nginx dosyasinda geciyorsa `conflicting server name` uyarisi alinir.
Bu durumda eski/tekrar eden site dosyasi devre disi birakilmalidir.

## 3. SSL Standardi

### Tercih edilen: wildcard SSL

Tum firma subdomainlerini kapsar:

```bash
certbot certonly --manual --preferred-challenges dns \
  -d volkaportal.com \
  -d "*.volkaportal.com"
```

Bu yontemde Certbot bir TXT kaydi ister. Spaceship DNS tarafinda istenen TXT kaydi eklenir.

Avantaj:

- Yeni firma acildiginda tekrar sertifika genisletmeye gerek kalmaz.
- `ornekfirma.volkaportal.com` gibi yeni subdomainler otomatik SSL kapsamina girer.

### Gecici / tekil yontem

Wildcard SSL alinana kadar tekil subdomainler sertifikaya eklenebilir:

```bash
certbot --nginx \
  -d volkaportal.com \
  -d www.volkaportal.com \
  -d erprefabrik.volkaportal.com \
  -d ornekfirma.volkaportal.com
```

Yeni firma sayisi arttikca bu yontem zorlasir. Uzun vadede wildcard SSL daha dogrudur.

## 4. Uygulama Environment Standardi

Production ortaminda beklenen degerler:

```text
APP_ENV=production
TENANT_BASE_DOMAIN=volkaportal.com
PUBLIC_BASE_URL=https://volkaportal.com
SESSION_COOKIE_DOMAIN=.volkaportal.com
DATA_DIR=/var/data/aksiyon-takip
```

Kontrol:

```bash
cd /var/www/aksiyon-takip
sudo -u aksiyon ./venv/bin/python - <<'PY'
from app import create_app
app = create_app()
print(app.config["SQLALCHEMY_DATABASE_URI"])
print(app.config["TENANT_BASE_DOMAIN"])
print(app.config["SESSION_COOKIE_DOMAIN"])
print(app.config["PUBLIC_BASE_URL"])
PY
```

## 5. Yeni Firma Yayina Alma Sirasi

1. Superadmin ile `Sirket Yonetimi` ekranindan firma ac.
2. Firma adres adini belirle: `ornekfirma`.
3. Ana domain alanini kontrol et: `ornekfirma.volkaportal.com`.
4. DNS wildcard varsa DNS adimi gerekmez.
5. Nginx wildcard varsa Nginx adimi gerekmez.
6. Wildcard SSL varsa SSL adimi gerekmez.
7. Wildcard yoksa yeni subdomaini DNS/Nginx/SSL tarafina tekil ekle.
8. `tenant-health` calistir.
9. Yeni firma subdomaininden login testi yap.

## 6. Kontrol Komutlari

```bash
curl -I https://volkaportal.com
curl -I https://erprefabrik.volkaportal.com
curl -I https://ornekfirma.volkaportal.com
```

Beklenen:

- `200`, `302` veya login sayfasina yonlendirme
- SSL uyari/hata yok
- `502 Bad Gateway` yok

Uygulama kontrolu:

```bash
sudo -u aksiyon ./venv/bin/python -m flask --app app:create_app tenant-health
sudo systemctl status aksiyon-takip --no-pager
systemctl status nginx --no-pager
```

## 7. Geri Donus

Nginx degisikligi sonrasi site acilmazsa:

```bash
nginx -t
ls -lah /etc/nginx/sites-enabled
```

Son calisan Nginx dosyasina geri don:

```bash
cp /etc/nginx/sites-available/volkaportal.bak /etc/nginx/sites-available/volkaportal
nginx -t && systemctl reload nginx
```

Sertifika problemi varsa:

```bash
certbot certificates
nginx -T | grep -n "ssl_certificate"
```

## Kabul Kriteri

- Wildcard DNS veya ilgili tekil subdomain DNS kaydi var.
- Nginx tek site dosyasinda `*.volkaportal.com` destekliyor.
- SSL sertifikasi subdomaini kapsiyor.
- Uygulama `Host` bilgisini kaybetmeden Gunicorn'a ulasiyor.
- Firma subdomaininden giren kullanici yalnizca kendi firmasinin verisini goruyor.

# Canli Kod Yayini

Tarih: 2026-09-15. Kullanici canliya alma icin acik onay verdi.
Kod release commit'i: 1cd6e45900f82ac637cd0f5afdf9c40b9c940d3e.
Baslangic commit'i: 048a4cfed87ea532730c1cf7ce38a9481e5d7eda.

## Yayinlananlar

- Oneride tum aktif kriterler puanlanmadan degerlendirme tamamlanmaz.
- Kismi puanlar saklanir; bos secim kendi eski puanini siler; gorev acik kalir.
- Kimlik tabanli puan kaydi, sahiplik/durum yetkileri, proxy/login/oturum
  guvenligi, dosya degisimi ve revizyon tekrar onayi duzeltmeleri.
- Guvenli production seed ve WSGI/factory baslangici.
- Runtime schema reconciliation ve user-identity/login-company migration'lari.

## Yayin Oncesi Kanitlar

- Guncel etkilenen moduller regresyonu: 73 passed, 69 warnings (142.76s).
  Bu, son commit'te butun test paketinin tekrar kosuldugu anlamina gelmez.
- Calisan Simulasyon ajani ek kontrolu: 31 passed, 28 warnings; gercek
  tarayici testi degil, Flask test client ve kod incelemesi.
- Gercek yedek kopyasinda Flask CLI upgrade ve tekrar upgrade basarili.
- Kopya veritabaninda tenant-health: tum kontroller OK.
- Planlamaci bagimsiz bellek ici rehearsal: 89 mevcut tablonun satir sayilari
  ve 8 degerlendirmenin tum degerleri korundu; model eksigi/FK ihlali yok.
- GitHub'a eksiksiz release commit'i gonderildi. Venv, gecici dosyalar ve
  kullaniciya ait lokal log degisiklikleri commit'e alinmadi.

## Son Yedek

```text
/var/data/aksiyon-takip/backups/full/volkaportal-backup-20260915-073113.zip
/var/backups/volkaportal/20260915-release/code-config-before-release.tar.gz
```

- Servis dururken tam yedek: 58,908,123 bayt, 203 upload, 205 checksum.
- backup-verify OK; bagimsiz CRC/tam checksum kapsami ve sayi/boyut kontrolleri OK.
- SQLite integrity/quick_check OK; duplicate user/parameter grup sayisi 0.
- Her iki arsiv sunucu disina kopyalandi:
  C:/Users/Asus/VolkaPortalBackups/20260915/.
- ZIP SHA256: a9423ee1ba3c3c885c14f9b0ad9847de07381886c4397988afad9292adf662b7.
- Kod/config SHA256: d6716954c2f59335fcfb53e87bc60a03d4e81690021ca5ccf24369740c4afba8.
- Yerel ve sunucu SHA256 degerleri eslesti. Hassas arsivler Git'e alinmaz.

## Canli Dogrulamalar

- Aktif Python 3.12.13; venv-py312, Gunicorn 23, iki worker, app:create_app().
- Servis kapaliyken sabit release'e fast-forward; requirements kurulumu ve pip check OK.
- Gercek DB head: 202609150002. tenant-health: 45 OK, 0 WARN, 0 FAIL.
- Mevcut tum tablo satir sayilari ve tum degerlendirme degerleri korunmus.
- Tum model tablolari/kolonlari mevcut; FK ve integrity OK; yeni kullanici
  bazli UNIQUE mevcut, eski isim bazli UNIQUE kaldirilmis.
- Servis yeniden acildi; yeni baslangic loglarinda traceback/eksik kolon yok.
- https://volkaportal.com/login HTTP 200.
- https://erprefabrik.volkaportal.com/login HTTP 200.
- https://sagiroglucelik.volkaportal.com/login HTTP 200.
- Canli nosniff, SAMEORIGIN, CSP, HSTS, no-store, referrer/permissions basliklari
  ve Secure/HttpOnly/SameSite=Lax cookie goruldu.
- Nginx X-Real-IP=$remote_addr, X-Forwarded-For=$proxy_add_x_forwarded_for,
  X-Forwarded-Proto=$scheme ayarlarini kullaniyor.

## Operasyon Notlari

- Systemd durdurma kaydi 07:31:09 UTC, yeniden baslatma 11:30:37 UTC.
  Hazirlik ve uygulama arasinda uzun duraklama oldu; servis bu aralikta
  kapali kaldi. Gelecek yayinlarda bakim islemi kesintisiz tek otomasyonla
  ve bakim zaman asimi/guvenli geri donus mekanizmasiyla yonetilmeli.
- deneme.volkaportal.com DNS cozumlenmiyor. --resolve ile dogrudan testte de
  sertifika bu alan adini kapsamiyor; TLS dogrulamasi kapatilmadi. Mevcut demo
  alaninin DNS ve SSL kurulumu ayrica tamamlanmali. Iki uretim firmasi etkilenmiyor.
- Gercek kullanici parolalari degistirilmedi, hesaplar silinmedi. Eski bilinen
  parolali hesap envanteri ve SECRET_KEY yonetimi halen ayri guvenlik isi.
- Tum canli CRUD/rol/mobil/posta senaryolari bu yayin smoke testiyle kanitlanmadi;
  tum-site-tamamlandi checklist'i isaretlenmedi. WHOLE_SITE_AUDIT raporundaki
  kalan riskler gecerlidir. Restore/downgrade uygulanmadi.

# UI Canli Yayin Kaydi - 29 Eylul 2026

## Sonuc

- Durum: Canliya alindi; yayin sonrasi kontroller basarili.
- Urun sahibi onayi: "Tamam canliya al".
- Uygulama surumu: `0f4702312ce1bd3f81bd17e3c0e7635870579e2b`.
- Onceki surum: `0ddfb2b62d94e7dd87baf93c96d81a4f5b052e04`.
- Statik dosya surumu: `20260929-workspace-ui`.
- Servis baslangici: 29 Eylul 2026, 10:54:25 UTC (13:54:25 Istanbul).
- Python: 3.12.13. Alembic head: `202609280002`.

Tasarim ve hata duzeltmeleri [UI inceleme kaydinda](UI_REVIEW_2026-09-29.md).
Yeni sol menu, dar ikon modu, mobil/tablet gezinmesi, ortak form/tablo stilleri,
mobil filtreler ve rapor katalogu bu surumle yayina alindi.

## Ajan Kontrolleri

- Planlamaci ve UX incelemelerinin ardindan kullanici onayi alindi.
- QA ve Regresyon ajani yayin oncesi 33 odakli Python testini tekrar calistirdi;
  tamami basarili. Son surumde tarayici kontrolleri de tekrarlandi.
- Veri ve Migration ajani sema degisikligi olmadigini dogruladi. Istedigi tam
  checksum kapsami ve yedek kopyasinda no-op migration provasi tamamlandi.
- Release ve DevOps incelemesindeki cache, yedek, fast-forward ve saglik
  kontrolleri uygulandi. Canliya alma onayi urun sahibinden geldi.

## Yedek ve Veri Guvenligi

Yedek alinirken uygulama ve arka plan yazicilari durduruldu. Yayin sonrasi
uygulama ile hatirlatma/webhook zamanlayicilari yeniden baslatildi.

- Sunucu yedegi:
  `/var/data/aksiyon-takip/backups/ui-20260929-0f470231/volkaportal-backup-20260929-105055.zip`
- Sunucu disi dogrulanmis kopya:
  `C:\Users\Asus\VolkaPortalBackups\20260929-ui\volkaportal-backup-20260929-105055.zip`
- SHA-256: `081967612b438d0b64e36e5f1af177c0bc56048359f8c486cb5486da52f2d87b`.
- Boyut: 59.180.295 bayt; 203 yuklenmis dosya; 205 checksum girdisi.
- ZIP CRC, dosya boyutlari, her dosyanin SHA-256 degeri ve manifest kapsami
  bagimsiz olarak dogrulandi. Yerel kopyanin erisim izinleri kisitlandi.
- SQLite `quick_check` ve `integrity_check`: basarili; 149 tablo.
- Geri yukleme dry-run: basarili; canli veriye geri yukleme uygulanmadi.
- Izole yedek kopyasinda `db upgrade`: basarili, veri parmak izi degismedi.
- Kod gecisi oncesi/sonrasi canli veritabani parmak izi ayni kaldi.
- Canlida migration, bagimlilik kurulumu veya sirket ayari degisikligi gerekmedi.
- Sunucudaki sinirli erisimli kanit:
  `/var/backups/volkaportal/ui-20260929-0f470231/evidence.json`.

## Test Sonuclari

- [x] 33 odakli Python testi.
- [x] Son uygulama surumunde 24 gezinme senaryosu.
- [x] Son uygulama surumunde 500 sayfa/ekran boyutu kontrolu; hata listesi bos.
- [x] Inceleme asamasinda 18 etkilesim ve 6 dokunmatik senaryo.
- [x] Inceleme asamasinda 390, 768 ve 1440 px donemli Excel indirme.
- [x] Alti rolun menu gorunurlugu ve arama sinirlari.

Tarayici kontrolleri ayri, gecici test verisiyle yapildi. Canli sistemde kayit
olusturma, duzenleme veya silme senaryosu calistirilmadi.

## Canli Kontroller

`volkaportal.com`, `erprefabrik.volkaportal.com` ve
`sagiroglucelik.volkaportal.com` icin:

- [x] `/login`, `/service-worker.js` ve `/offline`: HTTP 200.
- [x] Her adreste alti CSS/JS dosyasinin hash'i yayin commit'iyle ayni.
- [x] Statik dosya surumu ve service worker cache yenilemesi dogru.
- [x] Uygulama, hatirlatma ve webhook zamanlayicilari aktif.
- [x] Servisin yayin sonrasi hata seviyesindeki journal kayitlarinda girdi yok.

Iki sirket baglaminda sunucu icinden oturumlu, salt okunur render kontrolleri:

- Ana sayfa, Dokuman Listesi, IF Yonetimi ve Rapor Merkezi: HTTP 200;
  yeni menu ve surumlu arayuz kaynaklari mevcut.
- Rapor Merkezi katalogu masaustunde acik.
- Beton Deneyi: HTTP 403. Iki sirketin mevcut `quality_tests` ve
  `quality_test_concrete` ayarlari kapali; bu beklenen erisim kisiti.
  Ayarlar degistirilmedi. Beton Deneyi arayuzu gecici test ortaminda denendi.
- Uretim route haritasinda `__ui` test giris yardimcisi yok.

## Sinirlar ve Geri Donus

Tum backend test paketi bu UI yayininda tekrar calistirilmadi. Fiziksel
Android/iOS ve Safari testi yapilmadi; tarayici kontrolleri Chromium
emulasyonudur. Tum is akisi/yetki kombinasyonlari veya sabit 60/144 FPS
garantisi verilmez.

Yayin fast-forward ile yapildi; mevcut yerel loglar ve sunucudaki `venv/`
korundu. Veritabani semasi degismedigi icin yalniz UI sorunu durumunda once
uygulama kodu geri donusu degerlendirilmelidir. Veri geri yuklemek yeni
kayitlari kaybettirebilir; otomatik uygulanmaz. Geri donus karari urun
sahibinindir ve onceki surum ile dogrulanmis yedek yukarida kayitlidir.

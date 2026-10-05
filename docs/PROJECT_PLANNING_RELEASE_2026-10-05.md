# Proje Yonetimi / Planlama Yayini

## Kapsam

Checklist maddesi: `module_project_planning`. Sonraki madde olan
`module_project_gantt` bu yayinin kapsami disindadir.

Proje sahibi, baslangic ve bitis tarihi, amac, gorev sorumlusu ve termin
kaydedilir. Gorevler tamamlandiginda ilerleme tamamlanan aktif gorevlerin
oranindan hesaplanir. Proje taslaktan aktife, tamamlanmaya ve arsive gider;
kapanis ve arsiv gerekceleri audit kaydinda tutulur. Gorevlerim, uygulama ici
atama bildirimleri ve yetkili kullanicilar icin Excel raporu baglidir.

## Yetki ve Veri

- Tum kayitlar secili sirketle sinirlanir. Sirket secmeyen global yonetici
  proje kaydina erisemez.
- Olusturan, yoneten ve gorev alan kisi yalnizca ilgili projeyi gorur;
  sirket genelini gorme yetkisi ayridir. Varsayilan salt goruntuleyici rol,
  sirketin tum projelerini okur; degistirme ve rapor indirme yetkisi yoktur.
- Proje/gorev degisikliklerinde iyimser surum kontrolu ve audit vardir.
- Eski gorev sahibine veya eski termine ait uygulama ici bildirimler, yeniden
  atama veya termin degisiminde kaldirilir.
- Tamamlanmis ve tamamlanmadan arsivlenen proje ayri belirtilir. Arsiv
  gerekcesi ayrintida, proje Excel'inde ve Rapor Merkezi proje ciktisinda gorunur.
- Firma, proje ve sorumlu baglari SQLite FK kontrolu kapaliyken de yeni
  proje tablolarina ozel tetikleyicilerle korunur. Eski tablolarda genel
  FK ayari degistirilmez.
- Eski kayitlar topluca projeye aktarilmaz. Mail gonderimi bu akisla
  tetiklenmez; gorev atamalari uygulama ici bildirim uretir.

## Canliya Alma

1. Kod incelemesi, rol senaryolari, mobil kontrol, testler ve migration
   provasi tamamlanir.
2. Yazicilar durdurulur. Tam yedek olusturulur, dogrulanir, geri yukleme
   provasi yapilir ve sunucu disina ayni SHA256 ile kopyalanir.
3. Taze yedekte migration upgrade/downgrade/upgrade provasi yapilir.
4. Temiz hedefe fast-forward kod yayini ve yalniz upgrade uygulanir.
5. `scripts/project_planning_release.py configure` yalniz yeni proje
   yetkilerini ve eksik proje modul kayitlarini ekler.
6. Servis, her tanimli sirket alan adinda dis HTTPS, tenant/rol smoke ve
   loglar kontrol edilir. Canlida hesabi olmayan roller istisna olarak
   kaydedilir; rollerin tumu otomatik test ortaminda ayrica dogrulanir.
7. Yalniz `module_project_planning` checklist maddesi `mark` ile isaretlenir.
8. Onceden acik zamanlayicilar geri acilir ve son servis durumu kontrol edilir.

Basarisiz yayinda once kod onceki surume fast-forward ile doner; yeni tablolar
korunur. Canli veritabaninda downgrade veya yedek restore uygulanmaz.

## Kanit

- Eski yedek kopyasinda iki migration testi gecti; 156 mevcut tablo korundu.
- Yeni proje tablolari icin FK kapali yedi veri butunlugu denemesi gecti.
- Ilk genis regresyonda 81 test, son degisikliklerden sonra 82 test gecti.
  Proje ve minimal migration testleri 26/26; eski yedek provasi ayrica gecti.
- 390, 768 ve 1440 px tarayici akisi gecti; tablette liste islemi gorunur.

## Canli Sonuc

- Uygulama kodu `f2674f6`; checklist komutunun HTTPS/CSRF duzeltmesi
  `786eafd`. Ilk isaretleme denemesi guvenli HTTPS oturumu olmadigi icin
  kayit degistirmeden durdu; duzeltilen komut basariyla calisti.
- Son genis regresyon 82/82; yayin komutunun son degisikliginden sonra
  proje, rapor merkezi, rapor tasarimcisi ve tenant testleri 44/44 gecti.
  HTTPS CSRF checklist testi ayrica gecti.
- Taze tam yedek:
  `/var/data/aksiyon-takip/backups/project-planning-20261005/volkaportal-backup-20261005-062542.zip`.
  204 upload; checksum, quick_check, integrity_check ve restore dry-run OK.
- Sunucu disi kopya: `C:/Users/Asus/VolkaPortalBackups/20261005-project-planning/`.
  SHA256 iki tarafta da
  `98a8b414e58e0ac634d3a659adb8272d4dee7229c5eb509077491411aef06379`.
- Taze yedekte iki migration testi gecti; 156 eski tablo korundu.
  Canli migration head `202610030001`, tenant-health OK, 10 yeni SQLite
  koruma tetikleyicisi yerinde. Proje ve gorev sayisi sifir; test verisi eklenmedi.
- Uygulama ici sirket/rol smoke: 6 kontrol gecti. Canli hesap bulunmadigi
  icin Deneme firmasinda temsilci/personel/goruntuleyici, Sagiroglu Celik'te
  departman yoneticisi/personel/goruntuleyici rolleri gercek hesapla
  denenemedi. Bu roller otomatik testlerde sinandi.
- Ana alan ve Er Prefabrik ile Sagiroglu Celik alanlarinin HTTPS girisleri
  200. `deneme.volkaportal.com` dis DNS'te cozulmuyor; mevcut test firmasina
  dis erisim sorunu bu yayindan bagimsizdir.
- Paket kurali korundu: ISO cekirdek firmada proje modulu acik; iki `custom`
  paket firmada yeni modul varsayilan olarak kapali. Super Admin, sirket
  modulu ayarindan bunlari ayri ayri acabilir.
- `module_project_planning=1` olarak dogrulandi. `module_project_gantt`
  isaretlenmedi. Uygulama ve iki timer aktif; yayin sonrasi hata seviyesi
  servis gunlugu bos.

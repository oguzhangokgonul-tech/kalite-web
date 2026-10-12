# Musteri Geri Bildirimleri - 12 Ekim 2026

## Kapsam

- Personel tarafindan yeni geri bildirim acma; musteri e-postasi ve dogrulamasi gerektirmez.
- Musteri/proje, kaydeden, bildirim tarihi, icerik, birim, sorumlu, islem ozeti, termin ve sonuc takibi.
- Once/sonra icin birden fazla istege bagli PNG/JPEG. Kayittan sonra da eklenebilir.
- Kapali kayitlar listede tutulur ve gecikmis sayilmaz. Kapanis tarihi sistemce yazilir.
- Excel raporuna proje, kaydeden, islem ozeti, termin, kalan gun ve sonuc alanlari eklenir.
- Mevcut dis musteri portali korunur; personel kayitlari ayri kaynakla tutulur, musteri takip e-postasi uretilmez.

## Yetki ve Veri

- `customer_portal.create` yeni kayit yetkisidir; sistem yonetim, yonetim temsilcisi, departman yoneticisi ve personel rollerine eklenir.
- Atama ayri yetkidir. Atama yetkisi olmayan kullanici baska sorumlu/birim atayamaz, kendi actigi kaydi gorebilir.
- Sorumlu adaylari aktif, ayni firmada ve geri bildirim goruntuleme yetkisine sahip olmalidir.
- Gorseller ic paylasimdir. Onizleme/indirme kayit, firma ve dosya yetkisine tabidir.
- Gorseller gercek decode, 20 milyon piksel siniri, dosya boyutu/kota ve istek basina 12 dosya kontrolunden gecer; yeniden kodlanir, EXIF temizlenir.
- Basarisiz coklu yukleme/DB islemi dosyalari geri temizler. Arsiv kayitlarina yeni not/gorsel eklenemez.
- Kritik degisiklikler audit kapsaminda; ic kayitlar Gorevlerim, termin paneli ve mevcut bildirim politikasi ile baglidir.

## Kontrol

- Birlesik etki alani testi: 89 test basarili; son sorumlu secimi daraltmasi icin 6 hedefli test de basarili.
- Bagimsiz QA: rol, tenant, CSRF, dosya erisimi ve geri alma senaryolari.
- Tarayici: 390, 768, 1440 pikselde liste/form/detay; sayfa tasmasi ve JavaScript hatasi yok.
- Mobil tarayici: iki gorselle yeni kayit, gorsellerin yuklenmesi, islem/sonuc kaydi, kapanis ve Excel indirme basarili.
- Migration: eski dosya kaydi korunarak upgrade/downgrade/upgrade provasi.
- Graphify yalniz yerel AST ile yenilendi; harita deploy/commit kapsaminda degil.

## Yayin Durumu

Lider onayiyla 12 Ekim 2026 tarihinde canliya alindi. Ozellik commit'i: `5d5b118e093922d517016ee145e2b2369b1d74dc`.
Canli migration: `202610120001`. Yayin oncesi birlesik 89 test tekrar basarili.
- Yeni tam yedek: `volkaportal-backup-20261012-175122.zip`, 59.400.237 bayt, 204 ek dosya.
- Sunucu klasoru: `/var/data/aksiyon-takip/backups/customer-feedback-release.oxdYuHlC/archive/`.
- Sunucu disi kopya: `C:\Users\Asus\VolkaPortalBackups\20261012-customer-feedback\`.
- SHA256: `09ae36c36c834aacf75a54be69ac8272f2e2a05972fcf4256b2d1e300f6b7a6d`.
- Checksum, SQLite integrity ve restore dry-run basarili. Taze yedek kopyasinda upgrade/downgrade/upgrade ile 165 tablonun onceki kolon degerleri korundu.
- Canlida eski musteri kayitlari, mesajlar, dosyalar, tokenlar ve kontrol edilen diger is kayitlarinin ozetleri degismedi.
- Yeni olusturma yetkisi mevcut bes sistem rolune hedefli eklendi; baska rol yetkileri sifirlanmadi.
- Ana alan adi ve iki sirket giris sayfasi HTTPS 200. Uygulama, nginx, hatirlatma ve webhook zamanlayicilari aktif; son servis hata logunda kayit yok.
- Canli verinin gecici kopyasinda iki sirket icin kimlikli liste/yeni form ve yetkili Excel GET kontrolleri basarili; canli is verisine test kaydi yazilmadi.
- Bu yayin turundaki ajan cagrilari kullanim sinirina takildi; onceki bagimsiz QA kanitina ek olarak yayin testleri ve migration provasi ana ajan tarafindan tekrar yurutuldu.
Downgrade dosyalari silmez fakat once/sonra siniflandirmasini kaybettirir; geri donuste yedek gereklidir.
Tum repo testleri degil, etkilenen modul ve baglantili akislar test edilmistir.

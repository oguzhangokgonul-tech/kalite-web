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

Bu is icin canliya alim yapilmadi. Yerel onizleme ayri, sentetik veritabaninda calisir; gercek musteri verisi kullanmaz.
Yayin oncesi dogrulanmis yeni yedek alinmali, `202610120001` migration'i uygulanmali ve servis/HTTP kontrolleri yapilmalidir.
Downgrade dosyalari silmez fakat once/sonra siniflandirmasini kaybettirir; geri donuste yedek gereklidir.
Tum repo testleri degil, etkilenen modul ve baglantili akislar test edilmistir.

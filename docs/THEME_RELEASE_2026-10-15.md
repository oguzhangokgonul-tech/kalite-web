# Acik / Koyu Tema - 2026-10-15

## Kapsam

- Giris ekraninda ve uygulama ust cubugunda gunes/ay tema dugmesi.
- Acik tema varsayilan; mevcut acik renkler korunur.
- Tercih ayni tarayicida origin + sirket ID + kullanici ID kapsaminda saklanir.
  Giris oncesi misafir tercihi ayridir; cihazlar arasinda senkronizasyon yoktur.
- Depolama engelliyken tema mevcut sayfada degistirilebilir; sayfa yenilenince
  kalicilik garanti edilmez. JavaScript kapaliyken islevsiz dugme gizlenir.
- Ilk stil yuklenmeden tercih uygulanir; form verisi ve sayfa konumu korunur.
- Ayni kullanicinin acik sekmeleri storage olayi ile guncellenir.
- Bootstrap ve mevcut modul yuzeyleri koyu temaya uyarlanir; fotograflar,
  logolar, yuklenen dosyalar ve grafiklerin kendi renkleri ters cevrilmez.
- Yazdirma acik renkte kalir. Bagimsiz offline/rapor sayfalari ve gomulu
  dokumanlar uygulama temasindan bagimsizdir.

## Dogrulama

- Tema sunucu kontrati: 9 test; JavaScript davranisi: 27 test.
- Tema/PWA/mobil performans/rol navigasyonu/i18n: 44 Python testi gecti.
- Oturum kapatma ve sirket oturum izolasyonu: 10 Python testi gecti.
- Playwright: 320, 390, 768, 1440 pikselde toplam 32 koyu gorunum.
  Ana sayfa, Mobil Merkez, dokumanlar, kalibrasyon, personel, beton deneyi,
  aksiyon detayi ve dokuman yukleme ekrani kontrol edildi.
- Tarayicida tercih kaliciligi, sekme senkronizasyonu, kullanici ayrimi,
  kaydedilmemis form verisi, yazdirma ve JavaScript kapali giris kontrol edildi.
- Navigasyon regresyonu: 24 senaryo; alti rol, mobil menu, filtre ve klavye.
- i18n testleri HTML kok etiketinin tam metni yerine lang ozniteligini okur.
- QA, UX ve Release/Veri ajanlari bagimsiz inceleme yapti.
- Graphify yalnizca yerel AST ile yenilendi; ciktilari surume alinmadi.

## Yayin Kapilari

- Migration yok; model, route, yetki ve bildirim davranislari degismedi.
- Temiz hedef dosya listesi, testler, tam DB+uploads yedegi, sunucu disi SHA256
  dogrulamasi ve izole gercek geri yukleme tamamlanmadan yayin yapilmaz.
- Geri yukleme provasi tum tablo/veri/sema esitligini ve Alembic no-op kontrolunu
  yapar. Canli veritabaninda migration veya test kaydi olusturulmaz.
- Uc domain icin giris HTTP 200, JS/CSS HTTP 200 + MIME + SHA256,
  yetkisiz Mobil Merkez login yonlendirmesi ve servis/timer sagligi dogrulanir.
- Hedef oncesi commit: 790dba55225764d97b764c8493e20a642d06717d.
- Geri donus gerekirse bu temaya ait commit icin incelenmis git revert kullanilir;
  destructive reset veya veritabani geri yukleme gerekmez.
- Nihai yayin sonucu, commit ve yedek SHA'si yayin ciktilarinda raporlanir.

## Sinirlar

Tum modullerin her dolu/hatali/alternatif durumunun gorsel kabul testi yapilmadi.
Ortak yuzeyler ve temsili is akislarinda dogrulama yapildi. Canvas, harici
embed ve yuklenen dosya iceriklerinin kendi temalari bu degisikligin disindadir.

# Kullanici Profili Kayit Duzeltmesi - 2026-10-15

## Kok Neden

Kullanici formu gorev ve e-postayi kaydettikten sonra eski personel kaydindan
kullaniciya geri kopyaliyordu. Ayrica ad degisikligi mevcut personel kimligini
korumak yerine ada gore yeniden eslestirme yapabiliyordu.

## Degisiklikler

- Mevcut personel baglantisi ID ile korunur; acikca gonderilen ad, gorev ve
  e-posta ayni sirket icindeki personel, organizasyon ve aksiyon adlarina yansir.
- Gorevi temizlemek departman verisini silmez. NULL eski verinin departman
  fallback'ini korur; bos string acikca temizlenmis gorevi ifade eder.
- Personel listesi, iki rapor kaynagi ve organizasyon ayni display_title
  davranisini kullanir. Veritabani kolonu veya migration eklenmedi.
- Personel duzenleme formu da acikca bosaltilan gorevi korur; telefon gibi
  baska alanlar kaydedildiginde eski departman gorev olarak geri gelmez.
- Ayni ad/telefonla personel cakismasi 500 yerine anlasilir form hatasi verir;
  ilgili kullanici ve personel degisiklikleri birlikte geri alinir.
- Diger sirketlere ait veya korunmus hesaplara bagli kayitlar degistirilmez.
- Formda gonderilmeyen opsiyonel degerler korunur; uzunluklar sunucuda dogrulanir.
- Rol duzenlenebilen formda legacy izin kutulari salt okunur Kayitli Yetkiler
  ozeti olur. Rol/ek izin atama denetimleri ve eski yetki duzenleme akisi korunur.
- Basarisiz kayitta gizli olmayan form degerleri korunur; parola geri yazilmaz.
- Kullanici, personel ve organizasyon degisiklikleri mevcut audit kapsamindadir.

## Kontroller

- QA ajani: profil senaryolari, rol/yetki/tenant sinirlari, rollback ve audit.
- Planlama/Guvenlik/Veri ajani: kapsam, departman korumasi, yetki davranisi,
  release ve migration etkisi incelemesi.
- UX ajani: hata sonrasi form durumu ve kayitli yetkiler gorunumu.
- Chromium: 390/768/1440 pikselde kaydet, yeniden ac, temizle ve hatali kayit.
- Bagimsiz profil QA: 63 test gecti. Ilk istekteki dort hukuki metin kaydinin
  audit sayimini etkilememesi icin test baslangici form GET sonrasina alindi.
- Eski audit testi Superadmin rolu olmayan hesaba erisim bekliyordu; ayni
  hata baslangic commit'inde de dogrulandi. Test gercek super_admin roluyle
  hazirlanir; uygulamanin yetki kosulu gevsetilmedi.
- Gercek yedegin izole geri yukleme provasinda DB tablo/sema/veri esitligi,
  Alembic no-op, sentetik profil degisikligi ve audit dogrulanir.
- Canli kullanici verisi test icin degistirilmez. Mail ve hatirlaticilar testte kapali.

## Yayin

Baslangic commit: 3a866f99436f9a46c3f267a8f31c5c7b6e4076b0.
Yeni tam DB+uploads yedegi, off-host SHA256, izole restore ve bagimsiz testler
gecmeden yayin yapilmaz. Uc domain HTTP, servis ve timer kontrolleri tekrarlanir.
Yedekte eskiden bos gorevle dolu departman tutan kayit varsa yayin otomatik
durur; bu veriler icin ayri uyumluluk karari gerekir.
Geri donus gerekirse incelenmis revert kullanilir; destructive reset uygulanmaz.
Nihai test sayisi ve yayin SHA'si yayin sonucunda bildirilir.

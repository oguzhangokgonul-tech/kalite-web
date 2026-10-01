# Satisa Hazirlik Kapsam Karari - 29 Eylul 2026

## Karar

Urun sahibi karariyla asagidaki iki gelistirme satis oncesi aktif kapsamdan
ertelenmistir:

- `competitor_esignature`: E-imza entegrasyonu.
- `competitor_sso_mfa`: SSO ve iki asamali dogrulama.

Bu maddeler tamamlanmis sayilmaz. Katalog kimlikleri ve varsa onceki
`AppSetting` degerleri korunur; aktif ilerleme payina ve paydasina girmez.
Yeniden degerlendirme tarihi Lider karariyla belirlenir.

E-imza entegrasyonunun ertelenmesi, mevcut kullanici/zaman bilgili elektronik
is akisi onaylarini, dokuman okuma teyitlerini, arsiv kayitlarini veya audit
izlerini kaldirmaz. Bunlar sertifikali e-imza olarak tanitilmaz.

## Checklist Duzeni

- Tarihsel katalog: 142 madde.
- Aktif satis kapsami: 140 madde.
- Ertelenen: 2 madde.
- Aktif ilerleme ve kalan is, yalniz aktif kapsamdan hesaplanir.
- Ertelenenler salt okunur ayri bolumde gerekce ve karar tarihiyle gorunur.
- "Siradaki Is", tamamlanmamis ilk aktif maddeyi gosterir.
- Isareti kaldirilan mevcut madde `0` olarak korunur; runtime varsayimi onu
  eksik kayit sanarak yeniden tamamlamaz.

## Yerel Karar Destek Karari - 30 Eylul 2026

`competitor_ai_assistants` katalog kimligi geriye uyumluluk icin korunmus,
aktif madde adi "Yerel karar destek, mukerrer kayit, ozet ve rapor yardimcisi"
olarak netlestirilmistir. Harici uretken AI bu satis dilimine dahil degildir.

Rapor Merkezi icindeki asistan su kapsamda tamamlanmistir:

- Yetkili olunan Aksiyon ve IF/DOF kayitlarinin yonetim ozeti.
- Geciken, yaklasan, onay bekleyen ve veri kalitesi zayif kayitlar.
- Insan tarafindan dogrulanacak kok neden inceleme sorulari.
- Yerel baslik benzerligiyle mukerrer kayit inceleme adaylari.
- Her bulgu icin kaynak kayda dogrudan kanit baglantisi.
- Kaynak, bulgu, kayit ve calisma metadatasi iceren Excel ciktisi.
- Firma, modul ve kayit bazli yetki; yalniz ayri `reports.assist` izni.
- Kullanici, IP ve firma bazli dakika/gun calistirma sinirlari.
- Excel icin POST, CSRF, `reports.assist`, `reports.export` ve ayni kota.
- Ham kayit metni icermeyen, girdi/sonuc hash'li audit izi.
- En fazla 1.000 kayit tarama ve 300 yetkili kayit analiz siniri.

Asistan kaynak kayitlari degistirmez, onaylamaz, kapatmaz ve otomatik kok
neden karari vermez. Veri harici bir servise aktarilmaz. Global checklist
maddesini yalniz gercek `superadmin` hesabi, asistan veya Excel basariyla
calistiginda audit kaydiyla birlikte tamamlayabilir; musteri rolleri checklist
durumunu degistiremez.

Bir sonraki aktif madde `competitor_import_center` kaydidir.

## Veri Ice Aktarma Merkezi - 30 Eylul 2026

`competitor_import_center` maddesi kontrollu kurulum migrasyonu olarak
tamamlanmistir. Ilk satis surumu Departman, Personel, Kalibrasyon Cihazi ve
Tedarikci ust verilerini destekler.

- CSV ve XLSX icin revizyonlu bos sablonlar.
- En fazla 5 MB, 2.000 satir, guvenli arsiv ve formul kontrolleri.
- Veri yazmadan once zorunlu alan, tip, tarih, e-posta ve mukerrerlik kontrolu.
- Gecerli, atlanacak ve hatali satirlar icin ayri sayac ve indirilebilir hata raporu.
- Acik kullanici onayi olmadan olusturma, guncelleme veya silme yapilmamasi.
- Mevcut kayitlari degistirmeyen create-only ilk surum ve idempotent dosya hash'i.
- Hedef sirket, yukleyen, uygulayan, dosya SHA-256 ozeti ve sonuc sayilariyla audit izi.
- Sonradan degistirilmemis ve kullanima alinmamis kayitlar icin parti bazli geri alma.
- Yalniz gercek superadmin hesabi ve ayrik goruntuleme, hazirlama, uygulama,
  geri alma izinleri.
- Personel satirlarinin ham degerlerinin genel audit log'a kopyalanmamasi.

Checklist isareti yalniz gercek bir partide en az bir kayit basariyla
olusturuldugunda yazilir. Siradaki aktif madde `module_meeting_notes` kaydidir.

Gorunur TR/EN secicileri urun sahibi karariyla giris ve sol menuden
kaldirilmistir. Flask-Babel, ceviri kataloglari, sirket/kullanici dil alanlari ve
guvenli `/dil` endpointi gelecekte yeniden etkinlestirmek uzere korunur.

## Kabul Kaniti

- Checklist kimlik koruma, sayac, siradaki is, explicit `0`, yetkisiz POST,
  CSRF ve audit testleri.
- Yerel karar destek icin tenant izolasyonu, kayit bazli yetki, ayri calistirma
  izni, CSRF, hiz siniri, modul kapatma, Excel/audit ve sorgu limiti testleri.
- Telefon, tablet ve masaustunde checklist ile iki analiz kaynagi icin tasma,
  sonuc odagi, kanit baglantilari ve Excel indirme tarayici senaryolari.
- Veri aktarimi icin yetki, tenant izolasyonu, dosya/hash idempotency, onizleme,
  CSRF, XLSX/CSV guvenligi, atomik uygulama, hata raporu ve geri alma testleri.

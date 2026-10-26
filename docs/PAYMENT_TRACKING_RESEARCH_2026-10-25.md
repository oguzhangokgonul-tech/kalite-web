# Odeme takibi: urun ve uygulama kararlari

## Amac ve sinir

Bu modul banka veya muhasebe sistemi degildir. Sirketin bekledigi tahsilatlari ve
odeme yukumluluklerini, terminlerini, sorumlularini ve PDF kanitlarini ic kayit
olarak izler. Satin alma talebinden otomatik borc uretmez; herhangi bir transfer,
e-fatura, musteri portali veya harici kisilere otomatik e-posta yapmaz.

## Muadil urunlerden alinan dersler

| Kaynak | Gozlenen kullanim | VolkaPortal karari |
| --- | --- | --- |
| [Zoho Books - Reminders](https://www.zoho.com/ca/books/help/settings/reminders.html) | Vade oncesi/sonrasi hatirlatma; gerceklesince durma | 7, 1, 0 gun ve gecikme takibi; kayit kapaninca yeni hatirlatma yok |
| [Xero - Bill fields](https://central.xero.com/s/article/Bill-fields) | Karsi taraf, referans, tutar, vade ve ek | Iki yonlu kayitta bu minimum alanlar; proje numarasi istege bagli |
| [QuickBooks - Bills](https://quickbooks.intuit.com/learn-support/en-us/help-article/pay-bills/review-manage-bills-quickbooks-online/L8VbbnAd2_US_en_US) | Odenmemis, odenmis ve gecikmis gorunumleri | Acik, 7 gun icinde, geciken, tamamlanan, iptal ve arsiv filtreleri |
| [Odoo - Follow-up](https://www.odoo.com/documentation/18.0/applications/finance/accounting/payments/follow_up.html) | Gecikmeye gore aksiyon ve sorumlu takibi | Sirkete ozel ic sorumlu; merkezi, tekillestirilmis bildirim politikasi |
| [QuickBooks - Attachments](https://quickbooks.intuit.com/learn-support/en-us/help-article/invoicing/attachments-quickbooks-online/L8XvMBCgd_US_en_US) | Islem kaydina belge ekleme | PDF fatura/sozlesme/dekont yukleme, yetkili indirme ve audit izi |

## Ilk surum akislari

1. Yonetim yetkilisi Alinacak veya Yapilacak kayit acip karsi taraf, konu,
   toplam, para birimi, odeme secenegi, taksit sayisi/tarihleri/tutarlari ve
   opsiyonel takip sorumlusunu girer. Taksit toplami kayit toplamina esit olmalidir.
2. Isteyen PDF kanit ekler; 10 MB siniri, sirket depolama kotasi ve dosya
   imzasi kontrol edilir. Gercek virustarama/belge sandbox'i ayri bir gelecek
   yatirimidir; PDF imzasi tek basina zararsizlik garantisi degildir.
3. Her taksite ayri kismi gerceklesme girilebilir. Hareketler tarih, tutar,
   belge numarasi ve islemi yapan kisiyle saklanir; hatali hareket gerekceyle
   ters hareket olarak geri alinir. Tum taksitler tam odenmeden kayit kapanmaz.
   Cek/senet secimi tek basina odeme teyidi sayilmaz. Bu, muhasebe mutabakati degildir.
4. Acik taksitlerin terminleri 7 gun kala, 1 gun kala, gununde ve gecikmede
   merkezi hatirlatma mekanizmasina girer. Ilk surumde site ici bildirim
   varsayilan, e-posta kapali; firma bildirim politikasindan acilabilir.
5. Hatali/iptal kayit silinmez; gerekceyle iptal ve sonra arsiv uygulanir.
   Audit olayi, belge meta verisi ve eski dosya izi korunur.

## Yetki ve veri ilkeleri

- `payments.view`: iki listenin, detaylarin ve PDF'lerin okunmasi.
- `payments.manage`: kayit, duzenleme, gerceklesen tutar, iptal, arsiv ve belge.
- Varsayilan sirket yonetimi rolleri yetkilidir; diger personele gerekirse
  yalniz goruntuleme izni ayrica atanir. Genel personel/ziyaretci varsayilan
  olarak finansal tutarlari goremez.
- Butun kayitlar `company_id` ile ayrilir. Bildirimler sadece aktif, ayni
  sirketin bu sayfayi gorebilen yetkililerine yoneliktir. Dis musteriye
  bildirim gonderilmez; tutar veya PDF e-posta govdesine eklenmez.
- Iki kaydin ayni karsi taraf ve tutarla acilmasi bazen bilinclidir; otomatik
  engelleme yok. Karsi taraf, referans ve proje numarasinda arama vardir.

## Daha sonra degerlendirilecekler

- Eski kumulatif gerceklesmeler tekil hareketlere donusturulmez; tarihsel
  acilis bakiyesi olarak gosterilir. Sonraki odemeler ayri hareketlerdir.
- Satinalma, fatura, cari hesap veya ERP baglantisi; her biri icin ayri
  kimlik/idempotency ve hata kuyrugu tasarimi gerekir.
- Tahsilat/odeme onay zinciri, coklu para birimi kur hesaplama ve odeme emri.
- Toplu Excel aktarimi ve rapor; finansal verinin erisim/indirme politikasiyla
  beraber tasarlanmasi gerekir.

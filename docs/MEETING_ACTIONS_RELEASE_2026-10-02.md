# Toplanti Kararlarindan Aksiyon

## Kapsam ve Kullanim

Checklist: `module_meeting_action_decisions`.

Toplanti Notlari > toplanti > karar > Aksiyon Olustur.
Departman secilir; karar metni, sorumlu ve termin otomatik aktarilir.
Uzun baslik aksiyonda 160 karakterle ozetlenir; tam karar metni aciklamada
korunur. Gundem, tutanak ve katilimci listesi aksiyona kopyalanmaz.
Eski kararlar toplu veya migration sirasinda aksiyona donusturulmez.

## Is Akisi ve Yetki

- Uretim: acik karar ve yayinlanmis/kesinlesmis toplanti; toplanti duzenleme
  ve mevcut aksiyon olusturma yetkileri birlikte aranir. Toplanti modulu acik olmalidir;
  aksiyonlar mevcut sistemde ayri kapatilabilir modul degil, cekirdek islevdir.
- Taslak/arsiv toplantida uretim yoktur. Tekrarlanan istek ikinci aksiyon yaratmaz.
- Sorumlu aktif ve ayni firmada olmali; mevcut aksiyon akisinda kapanis talebi
  gonderebilmelidir. Yalniz goruntuleyici veya kapanis onaylayicisi sorumluysa
  olusturma acik hatayla reddedilir. Mevcut aksiyon yetkileri genisletilmez.
- Karar, aksiyon, baglanti, audit, sayac ve uygulama ici bildirim ayni transaction'dadir.
  Uretim sirasinda SMTP gonderimi yapilmaz. Standart aksiyon hatirlatmalari korunur.
- Bagli kararin ilk metni/sorumlusu/termini korunur; guncel sorumlu ve termin
  aksiyonda yonetilir ve yetkili kullaniciya toplantida ayri gosterilir.
- Bagli karar elle tamamlanamaz/yeniden acilamaz. Aksiyonun kapanis onayi ve
  gerekiyorsa etkinlik kontrolu tamamlaninca karar ayni transaction'da kapanir.
- Aksiyon yeniden acilirsa karar da acilir. Toplanti arsivlenmisse durum
  Tutanak Kesinlesti seviyesine doner; bu degisiklik audit'e kaydedilir.
- Bagli aksiyon silinemez. Tekrar kapanis talebinde onceki kanit dosyalari korunur.
- Gorevlerim'de bagli karar ikinci bir is olarak listelenmez; aksiyon gorevi surer.
- Iki yonlu link ve Excel aksiyon bilgileri bagimsiz kayit erisimine tabidir.
  Toplanti erisimi aksiyon erisimini otomatik vermez; duzenleyen ilgili kisi yapilmaz.

## Veri ve Yayina Alma

Yeni head: `202610020001`; onceki: `202610010001`.
Yeni `meeting_decision_actions` tablosu karar/aksiyon icin tekil baglanti,
firma, aktor ve zaman saklar. Mevcut tablo kolonlari degismez.
Runtime sema, model, Alembic ve audit kapsami birlikte guncellenir.

Canliya alma: temiz hedef diff, bagimsiz QA, migration provasi, yazarlari durdurma,
taze tam yedek, checksum/restore dry-run, sunucu disi kopya, fast-forward deploy,
migration, servis/HTTP kontrolu. Checklist yalniz bu kontrollerden sonra isaretlenir.
Geri donus kod ile yapilir; additive tablo korunur. Canlida downgrade/restore yoktur.
Test downgrade'u baglantilari siler; olusturulmus aksiyonlari silmez.

## Bilinen Kapsam Sinirlari

Genel SMTP outbox/retry degisikligi bu adimda yapilmadi. Mevcut diger aksiyon
islemlerinin commit oncesi e-posta davranisi bagimsiz teknik borc olarak kalir.
Tum depo testleri yerine etkilenen akis ve entegrasyon regresyonlari calistirilir.
Bu release, tum urun icin hatasizlik veya ISO uygunluk belgesi iddiasi tasimaz.

Firma esitligi uretim route'unda ve baglanti okuma/senkronizasyonunda denetlenir.
Baglanti tablosunun tekil anahtarlari DB seviyesindedir; bagimsiz FK'lar firma
esitligini tek basina zorlamaz. Dogrudan SQL ile tenant degistirme desteklenmez.
Genel SQLite FK etkinlestirme, eski veri ve tum migration'lar incelenmeden bu
dar release'e eklenmedi. Yeni import/API yazicisi eklenirse ayni invariant zorunludur.

## Dogrulama Kanitlari

- Son etkilenen regresyon paketi: 125 test gecti; basarisizlik yok.
- Bagimsiz son QA: 12 odakli kontrol gecti; yayin engelleyici bulgu yok.
- UX ajani masaustu/tablet/mobil dokuz ekran goruntusunu inceledi; blocker yok.
- Onceki toplanti migration testi: minimal DB ve eski yedekte iki test gecti.
- Guncel canli yedek kopyasi: 153 mevcut uygulama tablosu / 13.793 kayit;
  sekiz upgrade/downgrade/re-upgrade kontrolunde eski sema ve tum satirlar korundu.
- Yeni migration: 15 varsayilan/tekillik/FK kontrolu; model sema farki yok.
- Prova yedegi: `volkaportal-backup-20261002-054420.zip`, 204 upload,
  checksum, integrity ve restore dry-run OK; sunucu disi kopya hash eslesiyor.
- SHA256: `abe59398e2cedb976b3217ac28da28e07edfe60142e3c67507a5880c5a1370d2`.
- Bagimsiz QA: aksiyon akislarinda 5, rapor/bildirimlerde 4 regresyon gecti;
  eski kapanis bayragi uyumsuzlugu duzeltildi ve yeni regresyon eklendi.
- Mevcut rapor tasarimci testinin sabit 2026-10-01 termini zamanla gecikmis
  kayda donusuyordu; test verisi bugune gore ileri tarihli hale getirildi.
- Tarayici 390/768/1440 px: uretim, personel kapanis talebi, temsilci onayi,
  karar kapanisi, arsiv, Excel ve yatay tasma kontrolu gecti.

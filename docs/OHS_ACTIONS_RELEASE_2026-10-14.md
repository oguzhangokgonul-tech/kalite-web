# ISG Aksiyonlari: Deploy Kontrol Listesi

Durum: Lider'in canliya alma talebiyle 2026-10-14 tarihinde yayina alindi.
Uygulama commit'i: `5444d6bcd179e8a6e97f2e2633c8ec78b1847ed4`.

## Kapsam

`python -m scripts.ohs_actions_release configure` yalniz aktif firmalarin eksik
`CompanyModule(ohs_actions)` kayitlarini tum paketlerde acik ekler. Mevcut acik/kapali
secimler, pasif firmalar, diger moduller, roller, kullanici izinleri ve checklist
degerleri korunur. Mevcut `actions.*` izinleri kullanilir; yeni izin veya genis seed
yoktur. Degisiklik ve audit ayni transaction icindedir; tekrar calistirma `[]`
dondurur ve yeni audit yazmaz. Komut migration veya deploy yapmaz.

## Yayin Kapilari

- [x] Hedef diff, bagimsiz QA ve ilgili regresyon testleri dogrulandi;
  ilgisiz yerel degisiklikler, loglar, yedekler ve `graphify-out/` dahil edilmesin.
- [x] Yazma islemleri koordine edilerek taze DB + uploads yedegi alinsin;
  checksum, sunucu disi kopya, integrity ve geri yukleme provasi dogrulansin.
  Onceki uygulama commit'i, Alembic revision, modul secimleri ve firma bazli
  aksiyon/kategori sayilari kaydedilsin.
- [x] Yedegin izole kopyasinda `202610120002 -> 202610140001` upgrade,
  downgrade/upgrade provasi yapilsin; eski satirlar, FK, trigger ve indexler
  kontrol edilsin. Downgrade kategori kaybi asagidaki risk olarak kabul edilsin.
- [x] Onaydan sonra koordinator servis ortami ile migration uygulasin:
  `actions.action_category VARCHAR(16) NOT NULL DEFAULT 'general'`,
  `ix_actions_action_category` ve Alembic `202610140001` dogrulansin.
  Eski aksiyonlar `general`, mevcut `ohs` degerleri korunmus olmali.
- [x] Koordinator hedefli `configure` komutunu calistirsin; JSON cikti/audit ile
  eklenen firma kimliklerini saklasin. Ikinci calistirma `[]` olmali; mevcut kapali
  secimler, pasif firmalar ve `actions.*` izinleri degismemis olmali. Seed calistirilmasin.
- [x] `aksiyon-takip.service`, servis loglari ve HTTPS smoke dogrulansin;
  genel/ISG ayrimi, rol/firma izolasyonu, kapali modul erisimi ve mevcut aksiyon
  akislari kontrol edilsin. Checklist ancak ana ajanin ayri yayin dogrulamasi ile kapansin.

## Yerel Dogrulama

- Temiz commit worktree'sinde ISG release testleri: 160 basarili.
- Aksiyon/ISG ve alti rol: 85 test basarili.
- Bildirim politikasi/API/webhook: 128 test basarili; ek bildirim regresyonu
  107 test basarili. Paketler kismen ortustugu icin toplam benzersiz sayi degildir.
- Bildirim UI, migration ve hedefli release: 20 test basarili.
- Genel bildirim, mobil merkez ve tenant regresyonu: 85 test basarili.
- Tarayici: 390/768/1440 genisliklerinde sayfa tasmasi yok. Mobil merkezden
  fotograftan kayda, personele atamaya, termin degisikligine, kapanis kanitina
  ve yonetici onayina kadar akis tamamlandi. CSRF'siz istek 400 ile reddedildi.
  Tablet listesinde tablo kendi alani icinde yatay kaydirilabilir.
- Eski yedegin izole geri yukleme provasi: 166 tablo ve 204 dosya korundu;
  upgrade/downgrade/upgrade ve configure tekrari basarili. Taze canli yedek
  ile ayni kontroller yayin sirasinda yeniden yapildi ve gecti.
- Genel API/webhook kapsaminda ISG kayitlari disa acilmaz. Silinmis veya
  kategorisi dogrulanamayan eski aksiyon webhook kuyruklari da gonderilmez.
- Gercek alicilara test e-postasi gonderilmedi; SMTP testleri sahte tasiyici
  ile yapildi. Mevcut 08:30/gun ve tekrar politikalari degistirilmedi.

## Canli Yayin Kanitlari

- Onceki commit: `53aa5e24f008095e3eab035ed47ae130d9aea518`.
- Alembic: `202610140001`; ilk configure firma 1, 2, 3 icin modul ekledi,
  ikinci calistirma `[]` dondurdu. Roller ve ilgisiz checklistler degistirilmedi.
- Yedek: `volkaportal-backup-20261014-110558.zip`.
- Sunucu kanit dizini: `/var/data/aksiyon-takip/backups/ohs-release.GlctY3cF/`.
- Sunucu disi kopya: `backups/ohs-20261014/` (git/deploy disinda).
- Iki kopyanin SHA-256 degeri:
  `d7f22eab5ca4b1f370ee5b9db1c47e368a30efd1fb220b30edad7dc6d4b08395`.
- Taze yedek integrity/restore ve migration provasi basarili; eski is verileri,
  204 dosya ve genel aksiyon siniflandirmasi canli DB'de dogrulandi.
- Uc sirketin izole canli DB kopyasinda oturumlu liste/yeni kayit/mobil,
  dosya indirme, termin, firma izolasyonu ve kapali modul engeli dogrulandi.
  Gercek musteri verisine test kaydi veya disariya e-posta yazilmadi/gonderilmedi.
- `volkaportal.com`, `erprefabrik.volkaportal.com`, `sagiroglucelik.volkaportal.com`
  icin HTTPS login 200, oturumsuz ISG erisimi 302. Uygulama, nginx ve iki worker
  timer'i aktif; acilis logunda traceback/worker boot/database hatasi yok.
- Prova aracinda istekler arasi paylasilan test uygulama baglami duzeltildi;
  her HTTP istegi gercek uygulamadaki gibi ayri baglamda denendi.

## Rollback ve Veri Kaybi Uyarisi

Oncelik modulun kontrollu kapatilmasi ve veri koruyan duzeltmedir. Eski uygulamaya
donus kategoriyi dikkate almayip ISG kayitlarini genel aksiyonlarla karistirabilir;
salt kod rollback'i izolasyonun korundugu anlamina gelmez.

`202610120002` downgrade'i `action_category` kolonunu/indexini siler: aksiyon
satirlari kalsa da `general`/`ohs` ayrimi kaybolur. Yeniden upgrade tum kayitlari
`general` yapar; siniflandirma kendiliginden geri gelmez. Once firma/id/kategori
eslesmesi ve yeni kayitlar korunmadan canlida downgrade yapilmasin.

Yedekten donus yedek sonrasi kayit, dosya ve auditleri kaybettirebilir; Lider onayi
ve uzlastirma plani gerekir. Configure icin otomatik ters komut yoktur: yalniz
bu calistirmada eklenen modul kayitlari, sonraki kullanici degisiklikleri dikkate
alinarak degerlendirilmelidir. Eksik modul kaydi varsayilan acik olabilir; toplu
silme bir kapatma yontemi degildir. Mevcut secimler ve auditler silinmemelidir.

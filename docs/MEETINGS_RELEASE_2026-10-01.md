# Toplanti Notlari ve Karar Takibi

## Kapsam

Satis checklist maddesi: `module_meeting_notes`.
Sonraki ayri madde: `module_meeting_action_decisions`; otomatik aksiyon
olusturma bu surumde yoktur ve tamamlandi olarak isaretlenmez.

Sol menu: Toplanti Notlari. Genel sirket toplantilari YGG kayitlarindan ayridir.
Katilimci ve karar sorumlulari mevcut aktif sirket kullanicilarindan secilir.

## Akis

- Taslak: gundem, katilimcilar, yer, tarih, tutanak ve kararlar duzenlenir.
- Devam Ediyor: gundem ve katilimcilarla yayinlanir; karar takibi baslar.
- Tutanak Kesinlesti: tutanak zorunludur; acik kararlarin takibi devam eder.
- Arsiv: yalniz kesinlesmis, tum kararlari kapanmis toplantilar arsivlenir.
- Kesinlesmis tutanak tekrar acilabilir; arsiv kayitlari degistirilemez.
- Karar kapanisinda sonuc aciklamasi zorunludur. Fiziksel silme yoktur.

## Yetki

`meetings.view` kaydin olusturani, katilimcisi veya karar sorumlusuna okuma
hakki verir. `meetings.view_all` ve `meetings.manage` yalniz secili sirket
icerisinde genis erisim saglar. Global yonetici de sirket secmelidir.

- Yonetim temsilcisi: sirket genelinde yonetim ve rapor.
- Yonetim: sirket genelinde okuma, kendi toplantisini olusturma ve rapor.
- Departman yoneticisi: kendi toplantisini olusturma, ilgili kayitlar ve rapor.
- Personel: ilgili toplantilari okuma ve kendi kararini sonuclandirma.
- Goruntuleyici: yalniz ilgili toplantilari okuma.

CSRF, sunucu tarafli yetki, firma siniri, iyimser kilitleme ve audit izleri
liste, detay, guncelleme, gorev ve rapor akislari icin korunur.

## Release Kapilari

Tamamlanma isareti runtime veya migration tarafindan otomatik yazilmaz.
QA, migration provasi, yedek dogrulamasi ve canli smoke sonrasi yalniz bu
maddenin durumu guncellenir.

Yeni migration: `202610010001`, onceki head: `202609300001`.
Eski tablolarda alan silme/degistirme yoktur. Geri donuste once kod geri
alinir; yeni tablolar korunur. Canlida downgrade veya veri restore uygulanmaz.
Downgrade provasi yalniz gecici veritabani kopyasinda yapilir.

## Dogrulama

- 35 test: YGG, Gorevlerim, firma paketleri, donem raporlari, rol menuleri ve cikis.
- 38 test: toplanti akisi, rol/tenant siniri, CSRF, rapor merkezi ve rapor tasarimcisi.
- Bagimsiz QA bulgulari (katilimci silme audit izi ve ozel rapor filtresi) duzeltildi;
  iki regresyon testi bagimsiz ajan tarafindan da gecti.
- Tarayici: 390 / 768 / 1440 px; olusturma, karar, yayin, kesinlestirme,
  personel sonucu, arsiv, Excel ve yatay tasma kontrolleri gecti.
- Migration: minimal oncul ve gercek yedek kopyasinda upgrade / tekrar upgrade /
  downgrade / upgrade. 150 eski tablo ve 13.444 kayit degismedi; model farki yok.
- Canliya gecis oncesi tam yedek: `volkaportal-backup-20261001-130909.zip`;
  204 upload, checksum ve geri yukleme on kontrolu basarili.
- Yedek SHA-256: `428f222da86e535ad7a0316b81c9c2ad1e26498bf7eeba38ac0cc41a595d91aa`.

Otomatik test sayilari kismen ortak testleri icerir; tum depo test paketinin
bu release icin yeniden calistirildigi anlamina gelmez.

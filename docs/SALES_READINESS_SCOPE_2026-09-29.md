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

## Siradaki Adim

Siradaki aktif madde `competitor_ai_assistants` kaydidir. Ilk dilimde Rapor
Merkezi icinde yerel kayit analizi eklenmistir:

- Yetkili olunan Aksiyon ve IF/DÖF kayitlarinin durum ozeti.
- Yerel baslik sozcuk benzerligiyle inceleme adayi kayitlar.
- Kaynak kayda dogrudan baglanti ve yetkili Excel ciktisi.
- Acik firma kapsami, kayit bazli yetki ve en fazla 300 kayit siniri.
- Kaynak kayitlarda otomatik degisiklik, birlestirme veya kapatma yoktur.
- Harici servise veri gonderimi ve uretken AI yoktur.

Bu nedenle AI maddesi tamamlandi olarak isaretlenmez. Uretken ozet veya harici
AI entegrasyonu, saglayici, aktarilacak veri, saklama, KVKK ve insan onayi
sinirlari kararlastirildiktan sonra ayri dilimde ele alinir.

## Kabul Kaniti

- Checklist kimlik koruma, sayaç, siradaki is, explicit `0`, yetkisiz POST,
  CSRF ve audit testleri.
- Yerel analiz icin tenant izolasyonu, kayit bazli yetki, modul kapatma,
  Excel/audit, HTML kacis ve sorgu limiti testleri.
- Telefon, tablet ve masaustunde checklist ile iki analiz kaynagi icin tasma,
  klavye odagi, kaydetme ve Excel indirme tarayici senaryolari.

# Kisi bazli yetki yonetimi

## Karar

Roller kimlik/hiyerarsi ve varsayilan yetki sablonu olarak kalir. Her sirket
kullanicisi katalogdaki her izin icin uc karar tasir: `inherit` (satir yok),
`allow`, `deny`. Etkin karar sirasi korumali platform superadmin hesabi,
kisisel karar, rol izinlerinin birlesimi ve varsayilan ret seklindedir.
Kisisel ret, rolun verdigi ayni katalog iznini gecersiz kilar. Birden cok rol
atandiginda varsayilan izinler birlesir; kisisel karar yine usttedir.

Departman yoneticisi ve personeli rolleri standart baslangic sablonu olarak
kullanilmaya devam eder. Bu surum bir kisinin departman alanina bakip otomatik
rol atamaz: personel departmani serbest metin ve hesap baglantisi her zaman
tekil degildir. Sirkete ozel, surumlu departman sablonu ancak bu veri
eslestirmesi ve mevcut hesaplara yansima kurali netlestikten sonra eklenmeli.
Boylece bir sirketin sablon degisikligi diger sirketi etkilemez.
Mevcut rollerin kendisi globaldir: Superadmin tek bir rol sablonunu ayri bir
ekranda acip kapatabilir, ancak bu islem o roldeki tum sirket kullanicilarini
etkiler. Duzenlenen rol `permissions_customized` olarak isaretlenir: seed bu
rolun kaldirilmis izinlerini sonraki acilista geri eklemez. Dokunulmamis eski
roller ise varsayilan izinlerle uzlastirilmaya devam eder. Yeni anahtarlar bu
surumun migration'i ile onceki rollere bir kez eklenir.

## Uygulama

- `user_permissions.is_allowed` eklendi. Eski satirlar `allow` olarak kalir.
  `deny` icin `0`, `inherit` icin satirin silinmesi kullanilir.
- `/users/<id>/permissions` sayfasi tum katalogu gruplar, arar ve sablon ile
  etkin sonucu gosterir. Tek bir kullanici icin kaydeder. Profil duzenlemek
  kisisel kararlari sessizce sifirlamaz.
- `users.assign_roles` olmayan hesap duzenleyemez. Hedefin firma, silinme,
  korumali rol ve self-edit sinirlari sunucuda kontrol edilir. Firma yoneticisi
  kendisinde olmayan izni devredemez; tum form dogrulanmadan hicbir karar
  yazilmaz. CSRF global form korumasi gecerlidir.
- Her degisiklik eski/yeni kararlarla tenant kapsamli audit log'a yazilir;
  hedefin mevcut oturumu gecersizlestirilir.
- Onceden ayri tutulan aksiyon ve bildirim izin kontrolleri kisisel ret kararini
  dikkate alir. IF/DOF onaylari, oneriler, aksiyon yonetici kisayollari ve
  musteri geri bildirimi genel gorunumu ilgili katalog iznine baglandi.
- `super_admin` rolunun platform/tenant sinirlarini sirf bir kisisel izinle
  degistirmek mumkun degildir. Firma modulu kapaliysa kisisel `allow` modulu
  acmaz; kayit sahipligi ve atanma kontrolleri ayrica surer.

## Gecis ve geri donus

Alembic `202610270001` ve runtime schema uzlastirmasi ayni kolonu ekler.
Upgrade mevcut grant'leri korur ve tekrar calistirilabilir. Downgrade, `deny`
satiri varsa veri kaybini onlemek icin hata verir. Canliya cikmadan once
DB + upload yedegi, gercekci kopyada upgrade/downgrade/upgrade ve tam rol
matrisi testi gerekir. Bu belge bir canliya alma onayi degildir.

## Acik sinirlar

- Bu ekran katalog izinlerini yonetir; kullaniciya atanmis is/kayit ve sirket
  modulu durumu ayrica erisim kosuludur. Rol kimligiyle tanimlanan hiyerarsi
  ve is akisindaki atanma kosullari kisisel izin anahtari degildir.
- Sirket bazli, surumlu departman sablonlari ile sablon degisikliginin
  kullanicilara yayilma/onay kurali ayri bir urun karari olarak aciktir.
- Tum uygulama test paketi ve bagimsiz manuel rol/tenant testi tamamlanmadan
  uretim gecisi yapilmamalidir.

# Kalite Hedeflerinden Uygulama Plani

## Kapsam

- Satis checklist anahtari: `module_quality_objective_projects`.
- Kalite hedefi detayindan ayri komutlarla proje ve ilk gorev taslagi veya aksiyon olusturulur.
- Her hedeften en fazla bir proje ve bir aksiyon olusturulur. Eski aksiyon baglantisi degistirilmez.
- Proje aktivasyonu, gorevler, aksiyon kapanisi ve etkinlik kontrolu mevcut akislarini kullanir.
- Proje/aksiyon tamamlanmasi kalite hedefini otomatik kapatmaz. Olcum ve hedef onayi ayridir.
- Olusturmada tarihler hedef donemiyle sinirlidir. Sonraki yeniden planlama mevcut hedef modullerinin yetki ve denetim kayitlarina tabidir.
- Hedefin olusturma anindaki alanlari, secilen plan tarihleri ve kaynak parmak izi denetim kaydinda korunur.

## Yetki ve Veri

- Secili firma, hedef goruntuleme/yonetme, hedef kaydi kapsam yetkisi ve hedef modulde olusturma yetkisi birlikte gerekir.
- Kalite Hedefleri ve Projeler paket anahtarlari korunur. Aksiyonlar mevcut cekirdek islevdir; erisimi yetkilerle kontrol edilir. Musterinin paketi otomatik acilmaz.
- Form imzasi kullaniciya, firmaya, hedefe, islem turune ve incelenen hedef surumune baglidir.
- Eszamanli kaynak degisikligi kosullu guncellemeyle, cift olusturma benzersiz baglantiyla engellenir.
- Kaynak, hedef, gorev, bildirim ve audit ayni transaction icindedir.
- Kaynak baglantilari degistirilemez; bagli kayitlar silinerek izlenebilirlik bozulamaz.
- Firma ve goruntuleme izinleri yoksa bagli kaydin basligi ve detay baglantisi gosterilmez.
- Yeni aksiyon icin uygulama ici bildirim olusur. Taslak proje e-posta veya gorev bildirimi gondermez; mevcut aktivasyon kurallari uygulanir.

## Surum Gecisi

- Alembic: `202610080001` -> `202610090001`.
- Yeni tablo: `objective_plan_links`; mevcut is tablolarina kolon eklenmez.
- SQLite baglanti, firma, degistirilemezlik ve silme korumalari migration/runtime tarafinda aynidir.
- Downgrade baglanti tablosunu siler; sadece atilabilir prova veritabaninda denenmelidir.
- Canlida downgrade veya otomatik yedek geri yukleme yapilmaz. Hata durumunda yazicilar durdurulur ve ileri duzeltme tercih edilir.
- Canli yayindan once yeni tam yedek, arsiv dogrulamasi, geri yukleme provasi, sunucu disi SHA256 eslesmesi ve yedek kopyasinda upgrade/downgrade/upgrade gerekir.

## Kabul Kapilari

- [x] Davranis, rol, tenant, CSRF, tekrar istek, eski form ve audit geri alma testleri.
- [x] Mevcut kalite hedefi/proje/aksiyon regresyonu.
- [x] Migration ve onceki dogrulanmis yedek kopyasi provasi.
- [x] Mobil, tablet, masaustu form ve tasma kontrolu.
- [x] Bagimsiz guvenlik/is akisi incelemesi ve release aracinin otomatik testleri.
- [ ] Taze yayin yedegi, sunucu disi kopya ve migration provasi.
- [ ] Canli HTTP/servis kontrolu; yalniz ilgili checklist maddesinin isaretlenmesi.

## Yerel Dogrulama

- Ozellik ve migration: 179 basarili test. Iki CSRF beklentisi mevcut HTML yonlendirme/JSON 400 sozlesmesine uyarlanip yeniden calistirildi. Opsiyonel gercek yedek testi ayrica basarili.
- Kalite hedefi, proje, toplanti-aksiyon ve bagli aksiyon silme regresyonu: 108 basarili test.
- Release araci: 4 basarili test; eszamanli bagimsiz yazici testi: 1 basarili test. Toplam 293 farkli kontrol basarili. Tum depo test paketi calistirilmadi.
- Playwright: 390x844, 768x1024 ve 1440x900; 21 sayfa durumu, 6 basarili form gonderimi, gecersiz formdan toparlanma, klavye ve Turkce karakter kontrolleri. Sayfa tasmasi yok. Uzun tek satirli input degerleri standart yatay imlec kaydirmasi kullanir.
- Onceki yedek kopyasinda 46 GET kontrolu basarili; musteri kayitlari degismedi. Bazi sirketlerde acik kalite hedefi veya tum rollerden kullanici bulunmadigindan canli-veri rol kapsami kisitli. Eksik senaryolar sentetik testlerle kontrol edildi; canliya ornek kayit eklenmedi.
- Graphify yerel AST haritasi yenilendi; commit/deploy kapsaminda degil.
- Planlama/guvenlik incelemesi Zeno, model/migration Meitner, davranis testleri Bernoulli, Playwright Avicenna, release araci Goodall tarafindan baslatildi. Ajan kullanim siniri sonrasi kalan duzeltme, test ve yayin kontrolleri ana ajan tarafindan tamamlanir; tum ajanlarin kesintisiz bitirdigi iddia edilmez.

Siradaki checklist maddesi: `module_management_calendar`.

# VolkaPortal Ajan Calisma Kurallari

Bu dosya, Codex ve ona bagli ajanlarin VolkaPortal reposunda nasil calisacagini tanimlar. Her ajan bu kurallari kullanici talimatlarindan sonra gelen proje standardi olarak kabul eder.

## Yetki Sirasi

1. **Lider / Urun Sahibi: Oguzhan Gokgonul**
   - En ust karar merciidir.
   - Is hedefini, onceligi, kabul kriterini ve canliya alma kararini verir.
   - Ajanlar arasinda celiski olursa son karar Lider'indir.
   - Acikca onaylamadigi surece canli sunucuda riskli islem, veri silme, force push, destructive git komutu veya kapsam disi refactor yapilmaz.

2. **Kodcu Ajan**
   - Lider'den sonra uygulama yetkisi en yuksek ajandir.
   - Kod yazar, dosya duzenler, test ekler, test calistirir, commit hazirlar.
   - Mevcut Flask, SQLAlchemy, Jinja, Bootstrap Icons ve proje UI kaliplarini korur.
   - Kodcu Ajan bir istegi uygulamadan once yeterli baglam yoksa Planlamaci Ajan'dan kisa teknik plan ister.
   - Kodcu Ajan, Planlamaci Ajan'in veya Calisan Simulasyon Ajan'i bulgularini Lider onayi olmadan buyuk kapsamli refactora ceviremez.

3. **Planlamaci Ajan**
   - Isleri teknik ve urun checklistlerine boler.
   - Gereken model, route, template, test, yetki, migration, audit log ve deploy etkilerini belirler.
   - Mantiksiz, eksik, riskli veya gelistirilebilir kisimlari Lider'e bildirir.
   - Kod yazmaz; Kodcu Ajan'a uygulanabilir, dosya referansli plan verir.
   - Calisan Simulasyon Ajan'indan gelen kullanici deneyimi ve surec bulgularini toparlar, onceliklendirir.

4. **Calisan Simulasyon Ajan'i**
   - Sirket calisanlari ve sistem kullanicilari gibi davranarak ekranlari ve is akislarini dener.
   - Tek tek su rollere burunur:
     - Super Admin
     - Yonetim Temsilcisi
     - Yonetim
     - Departman Yoneticisi
     - Departman Personeli
     - Sadece Goruntuleyici
     - Aksiyon Sorumlusu
     - IF/DÖF Sorumlusu
     - Ic Denetci
     - Dokuman Kullanicisi
     - Musteri sikayeti kaydi acan kullanici
   - Her rol icin sunlari kontrol eder:
     - Sayfaya erisim mantikli mi?
     - Yetkiler dogru sinirlanmis mi?
     - Form alanlari kullanici icin anlasilir mi?
     - Yazilar tasiyor, ust uste biniyor veya tabloyu sikistiriyor mu?
     - Eksik, gereksiz veya mantiksiz alan var mi?
     - Kullanicinin isi bitirmesi icin dogal sonraki adim var mi?
   - Kod degistirmez.
   - Mantiksiz veya gelistirilebilir bulgulari once Planlamaci Ajan'a, kritik bulgulari dogrudan Lider'e raporlar.

## Standart Is Akisi

1. Lider hedefi verir.
2. Planlamaci Ajan hedefi kisa teknik plana cevirir.
3. Kodcu Ajan plani uygular.
4. Calisan Simulasyon Ajan'i farkli rollerle sonucu dener.
5. Planlamaci Ajan bulgulari onceliklendirir.
6. Kodcu Ajan gerekli bugfixleri yapar.
7. Testler calistirilir.
8. Lider'e degisiklik ozeti, test sonucu, commit hash ve siradaki adim bildirilir.

## Kodcu Ajan Kurallari

- Kod yazmadan once ilgili dosyalari oku.
- `rg` veya `rg --files` ile hizli arama yap.
- Manuel dosya duzenlemelerinde `apply_patch` kullan.
- Kullaniciya ait veya ilgisiz local degisiklikleri geri alma.
- `git reset --hard`, `git checkout --` ve benzeri destructive komutlari Lider acikca istemedikce kullanma.
- `flask-server.err.log`, `flask-server.out.log`, `venv/`, gecici dosyalar ve lokal loglar commit'e alinmaz.
- Yeni tablo veya kolon gerekiyorsa mevcut runtime schema yaklasimina uygun ekle.
- Coklu firma yapiyi koru: yeni kayitlarda `company_id`, sorgularda `scoped_query`, kayitlarda `assign_current_company` kullan.
- Kritik islemleri audit log kapsaminda tut.
- Yetki gerekiyorsa `PERMISSION_CATALOG`, rol tanimlari, menu gorunurlugu ve route kontrolu birlikte guncellenir.
- Yeni endpoint eklendiyse `MODULE_ENDPOINTS` ve sol menu aktif durumlari kontrol edilir.
- Formlar Turkce karakterleri bozmayacak sekilde yazilir.
- UI degisikliklerinde yazi tasmasi, tablo sikismasi ve mobil gorunum dusunulur.
- Degisiklikten sonra uygun testler calistirilir; mumkunse tum test paketi kosulur.

## Planlamaci Ajan Kontrol Listesi

- Hedef hangi modulu etkiliyor?
- Mevcut veri modeli yeterli mi?
- Yeni tablo/kolon gerekiyorsa canli veri icin guvenli mi?
- Yetki matrisi net mi?
- Audit log'a girmesi gerekiyor mu?
- Ana sayfa ozeti, Gorevlerim, Bildirimler veya Satis Checklist'i etkileniyor mu?
- Excel/PDF/rapor cikti ihtiyaci var mi?
- Testler hangi davranislari kanitlamali?
- Deploy sirasinda servis adi, migration ve rollback notu gerekiyor mu?

## Calisan Simulasyon Ajan'i Rapor Formati

Her rol icin rapor su formatta yazilir:

```text
Rol: Yonetim Temsilcisi
Senaryo: Yeni IF/DÖF kaydi inceleme
Sonuc: Basarili / Sorunlu
Bulgu: ...
Risk: Dusuk / Orta / Yuksek / Kritik
Oneri: ...
Planlamaciya Not: ...
Lider'e Not: ...
```

## Canliya Alma Notu

- Varsayilan servis adi: `aksiyon-takip.service`
- Standart sunucu kontrolu:

```bash
cd /var/www/aksiyon-takip
sudo -u aksiyon git pull
sudo systemctl restart aksiyon-takip
sudo systemctl status aksiyon-takip --no-pager
sudo journalctl -u aksiyon-takip -n 80 --no-pager
```

Yerel degisiklikler `git pull`u engellerse once Lider'e bilgi verilir ve guvenli stash komutu onerilir.

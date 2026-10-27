# VolkaPortal Guvenlik ve Dayaniklilik Kontrol Listesi

Baslangic: 27 Ekim 2026. Bu liste, satis oncesi guvenlik dogrulamasini
kanita baglamak icindir. Bir maddenin kodda bulunmasi, test edildigi veya
guvenli oldugu anlamina gelmez. `[x]` yalnizca yaninda belirtilen kanit
icin kullanilir. Durumlar: tamamlandi, acik, engelli, ertelendi.

## Kapsam ve kurallar

- Hedef: Flask/SQLAlchemy uygulamasi, sirket alt alan adlari, dosya yukleme,
  bildirimler, entegrasyon API'leri, yedekler ve Windows/Ubuntu dagitimi.
- Yerel otomatik testler bu calisma kapsamindadir. Canli ortamda yuk, aktif
  tarama, parola denemesi, veri degistiren siza testi veya hizmeti etkileyen
  islem yapilmaz. Bunun icin Lider'in hedef, zaman ve durdurma kosullarini
  ayrica onaylamasi gerekir.
- Siza ve yuk testleri once izole, uretime benzeyen bir ortamda ve sentetik
  firmalar/kullanicilarla yapilir. Musteri verileri test raporuna alinmaz.
- Her bulgu: kimlik, etkilenen surum/route, onem, asgari kanit, duzeltme,
  tekrar test ve kapatma karariyla izlenir. Gizli degerler rapora yazilmaz.
- Hedef referans: [OWASP ASVS 5.0.0](https://asvs.owasp.org/) ve
  [OWASP WSTG](https://wstg.owasp.org/). Bunlar kullanilarak kontrol secilir;
  herhangi bir sertifika veya tam kapsam uyumu iddia edilmez.

## 0. Envanter ve test kapisi

- [x] Ilk guvenlik envanteri ve ilgili test dosyalari belirlendi. Bu,
  tum route'larin incelendigi anlamina gelmez. Kanit: `app/config.py`, `app/__init__.py`,
  `docs/multi_tenant_security_checklist.md`, `tests/test_security_hardening.py`,
  `tests/test_tenant.py`, `tests/test_tenant_session_isolation.py`,
  `tests/test_workflow_security.py`, `tests/test_upload_safety.py`,
  `tests/test_backup_restore.py`, `tests/test_audit_log.py`.
- [x] Satis kapsamindaki e-imza ve MFA/SSO ertelemesi not edildi. Bunlar
  tamamlanmis guvenlik kontrolu olarak sayilmaz. Kanit:
  `docs/SALES_READINESS_SCOPE_2026-09-29.md`.
- [ ] Test edilen commit, ortam, alan adlari, izinli IP'ler, test hesaplari,
  test penceresi, trafik siniri ve acil durdurma kisisi belirlensin.
- [ ] Daha once sohbet, bilet veya loglarda paylasilmis olabilecek yonetici
  parolalari/API anahtarlari dondurulsun; SSH anahtari ve en az yetki
  politikasina gecis dogrulansin. Gizli degerler checklistte tutulmaz.
- [ ] Izole test ortaminda sentetik iki firma, tum roller, dosya ve entegrasyon
  ornekleri hazirlansin; test oncesi yedek ve geri yukleme provasi yapilsin.

## 1. Temel otomatik guvenlik kapisi

- [x] Ilk odakli oturum, anonim erisim, CSRF, guvenlik basliklari,
  tenant izolasyonu, dosya yolu/yukleme ve is akisi guvenligi testleri gecti:
  65 test. Tum route/rol matrisi henuz tamamlanmadi.
- [x] `pip-audit -r requirements.txt` ile ilk bagimlilik taramasi yapildi;
  Pillow 12.3.0 icin 37 kayit bulundu. Bulgular bu dosyada kaydedildi.
- [x] Pillow 13.0.0 ile ikinci `pip-audit -r requirements.txt` taramasi
  temiz sonuc verdi: `No known vulnerabilities found`.
- [x] Canli Python surumu Pillow 13 icin dogrulandi: 3.12.13. Tam regresyon
  ayrica acik kalir; odakli release testleri tam paket yerine gecerli sayilmaz.
- [ ] Gizli anahtar ve parola sizintisi icin git gecmisi ve dagitim
  yapilandirmasi yetkili kisilerce taransin; kanitlara sirlar kopyalanmasin.
- [ ] Uretim ayarlari dogrulansin: `SECRET_KEY`, HTTPS, cookie bayraklari,
  proxy/Host guveni, yedek erisimi, CSRF istisnalari ve guvenlik basliklari.
- [ ] Sunucu/servis sertlestirmesi kanitlansin: isletim sistemi yamalari,
  en az yetkili servis kullanicisi, SSH/yonetim erisimi, firewall, TLS ve
  reverse proxy ayarlari. Musteri ortami icin ayrica veri erisimi incelensin.
- [ ] Yukleme/indirme tip ve boyut sinirlari, arsiv acma ve dosya icerigi
  riskleri butun moduller icin envantere baglansin.

## 2. Yetki, tenant ve is akisi saldiri testleri (izole ortam)

- [x] Odemeler ilk dilim: alacak/borc yonlerinde goruntuleyici ile yabanci
  firma yoneticisi icin detay ve sekiz degisiklik rotasi test edildi.
  `tests/test_payment_tracking.py::test_payment_mutations_require_manager_and_matching_company`.
- [x] Odeme eki savunmasi: kayit metaverisi yabanci firmanin veya ayni
  firmanin baska modulunun dosyasini gosterse bile indirme 404; reddedilen
  yabanci dosya icin `downloaded` audit kaydi olusmuyor. Yeni dosya yolu
  siniri `app/payment_tracking.py` icinde. Mevcut gecerli indirme testi de
  gecti. Bu, butun dosya modullerinin dogrulandigi anlamina gelmez.
- [ ] Rol x firma x islem matrisi: liste, detay, olusturma, degistirme,
  silme, onay, rapor ve dosya indirme icin izinler sinansin.
- [ ] Yatay/dikey yetki atlama, baska firmaya ait ID ve dosya baglantisi,
  alt alan adi/oturum degisimi ve superadmin/sirket admini sinirlari denensin.
- [ ] Giris kilidi, sifre sifirlama/degistirme, oturum sonlandirma,
  CSRF ve tekrar oynatma senaryolari denensin.
- [ ] Girdi isleme ve cikti kodlama icin XSS, SQL injection, dosya yolu,
  SSRF ve acik yonlendirme testleri riskli route'larda yapilsin.
- [ ] Entegrasyon API'lerinde kimlik, imza, oran siniri, idempotency ve
  sirket kapsami denensin.
- [ ] Bagimsiz manuel siza testi raporu alinsin; yuksek/kritik bulgular
  duzeltilip tekrar testle kapatilsin.

## 3. Yuk, dayaniklilik ve toparlanma (izole ortam)

- [ ] Gercekci anonim/giris yapmis istek karmasi, modul dagilimi ve
  eszamanli kullanici hedefi Lider tarafindan belirlensin.
- [ ] Baslangic olcumu: p50/p95 gecikme, 4xx/5xx, CPU, bellek, DB kilitleri,
  disk, kuyruk ve mail isleme suresi kaydedilsin.
- [ ] Testten once Lider tarafindan sayisal kabul ve acil durdurma esikleri
  yazilsin: eszamanli kullanici, p95, 5xx orani, kaynak limiti ve toparlanma
  suresi. Baslangic olcumu olmadan rastgele kapasite hedefi kabul edilmez.
- [ ] Kademeli yuk, ani artis, uzun sureli kullanim ve toparlanma testleri
  kaynak limitleri ve durdurma esikleriyle calistirilsin.
- [ ] Yuk altinda firma izolasyonu, kayit tutarliligi, audit log ve dosya
  butunlugu tekrar dogrulansin.
- [ ] Darbogazlar giderilip ayni senaryolar tekrar calistirilsin; kapasite
  ve olceklenme siniri raporlansin.

## 4. Satis/release kapisi

- [ ] Tam regresyon, migration, yedek/geri yukleme ve canliya cikis provasi
  guncel commit uzerinde basarili olsun.
- [ ] Temiz hedef diff, rollback plani ve QA, Veri/Migration, Guvenlik ve
  Release/DevOps uzman kontrol raporlari kaydedilsin.
- [ ] Acik yuksek/kritik bulgu kalmasin; diger bulgularin sahibi ve tarihi
  olsun. Risk kabulunu ve canliya alma kararini yalniz Lider versin.
- [ ] Canliya alma sonrasi sadece dusuk etkili saglik, TLS, log ve HTTP
  smoke kontrolleri yapilsin. Canli yuk/siza testi ayri onaya baglidir.

## Bu turun kanit kaydi

- Tarih: 27 Ekim 2026.
- Durum: Ilk envanter tamamlandi. 65 odakli guvenlik testi gecti:
  `test_security_hardening.py`, `test_tenant.py`,
  `test_tenant_session_isolation.py`, `test_upload_safety.py`,
  `test_workflow_security.py`. Tum guvenlik kapsami veya tam regresyon
  tamamlandi denemez. Aktif siza/yuk testi yapilmadi.
- Bagimlilik bulgusu: `pip-audit -r requirements.txt`, Pillow 12.3.0 icin
  37 kayit bildirdi; duzeltme surumu 13.0.0. Gereksinim dosyasi 13.0.0'a
  guncellendi. Yerel Python 3.12.13 ortaminda sozlesme, musteri geri
  bildirimi, dosya ve dokuman akislari icin 88 test gecti. Canli Python
  surumu ve tam regresyon kontrol edilmeden release kapisi acilmaz.
- Ikinci bagimlilik taramasi: `pip-audit -r requirements.txt` temiz.
- 27 Ekim release oncesi: canli Python 3.12.13; musteri geri bildirimi,
  odeme migration, yedekleme ve dokuman yonetimi icin 31 odakli test gecti.
  Pillow PNG/JPEG onizleme testi eklendi. Tam pytest paketi bu turda
  tamamlanmadi; tam regresyon maddesi acik tutuldu.
- 27 Ekim ikinci tur: mevcut Odemeler/Sozlesmeler/Satin Alma modulleri
  paketi 49 testle gecti. Odeme indirmesinde metaveri yabanci firma yoluna
  degistirildiginde yeni test duzeltmeden once 200 ile kirmizi oldu; firma
  `payments` dizini sinirindan sonra 404 ile yesil oldu. Duzeltme sonrasi
  Odemeler ve tenant oturumu testleri 26 gecti; ek negatif dosya/yetki
  testleri 3 gecti. Bu turlar tam regresyon veya manuel siza testi degildir.
- Onceki `docs/WHOLE_SITE_AUDIT_2026-09-15.md` raporu tarihsel kanittir;
  bugunku surum icin dogrulama sayilmaz.

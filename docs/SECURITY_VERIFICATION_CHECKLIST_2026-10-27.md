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
- [x] Aksiyonlar ilk dilim: atanmis salt goruntuleyici termin, alt aksiyon
  olusturma/duzenleme/tamamlama/silme isteklerinde 403 alir; kayit degismez.
  Yabanci firma aksiyon ve alt aksiyon detay, duzenleme, silme ve ek indirme
  URL'leri 404 alir. Kanit: `tests/test_action_management.py`. Tum rol x firma
  x islem matrisi ve diger ek turleri henuz tamamlanmadi.
- [x] Aksiyon dosyasi ikinci dilim: ana ek, alt aksiyon kaniti, kayitli ve
  eski tek-dosya kapanis kaniti yalniz kaydin firmasindaki ilgili `actions`
  alt klasorunden indirilir. Yabanci firma, baska modul ve yanlis aksiyon
  klasoru metadata'si 404 verir; reddedilen istek `downloaded` audit kaydi
  olusturmaz. Kanit: `tests/test_action_management.py` dosya yolu matrisi.
  Bu butun modullerin dosya guvenligini kanitlamaz.
- [x] Aksiyon dosya sahipligi: ayni firmanin ayni `actions` alt klasorundeki
  baska aksiyona ait dosya metadata ile referans edilirse indirme 404 verir.
  Diger aksiyonun ana eki, alt aksiyon ve iki kapanis kaniti varyanti testle
  dogrulandi. Esdeger ama kanonik olmayan dosya yollari da reddedilir.
  Dosya yolunda kayit kimligi bulunmadigindan, artik baska bir
  kayit tarafindan referans edilmeyen yetim dosyanin sahipligi bu kontrolle
  kanitlanamaz; bu kalinti risk acik kalir.
- [x] Yeni aksiyon dosyalari icin sirket, aksiyon ve alt kayit kimlikli
  kalici klasor duzeni ile guvenli silme karari yazildi ve uygulandi.
  Kanit: `docs/ACTION_FILE_OWNERSHIP_2026-10-27.md`, aksiyon/ISG testleri.
  Bu kontrol tek basina yetim dosyanin tarihsel sahibini kanitlamaz.
- [x] Aksiyon dosyalari icin kalici manifest ve tombstone migration'i ile
  geri donus provasi uygulandi. Sahipligi kanitlanmayan eski dosyalar otomatik
  sahiplenilmez; eski referans varsa migration durur. Yeni yuklemelerde firma,
  aksiyon, alt kayit, boyut ve SHA-256 dogrulanir. Silinen yol yeniden acilmaz.
  Kanit: `202610300001`, dosya ve migration testleri, 30 Ekim izole canli DB
  kopyasi upgrade/downgrade/upgrade provasi. Tum modullerin dosya guvenligi
  veya bagimsiz siza testi tamamlanmis sayilmaz.
- [x] Eski duz-kok aksiyon dosyalari icin karar kaydedildi: genel
  `legacy_uploaded_file_path` geri dususu acilmaz. 27 Ekim canli salt-okunur
  envanterinde dort dosya alaninin tamami `0/0/0/0`; yayindan hemen once
  yeniden sayilir, dolu kayit varsa tasima plani olmadan release durur.
- [ ] Rol x firma x islem matrisi: liste, detay, olusturma, degistirme,
  silme, onay, rapor ve dosya indirme icin izinler sinansin.
- [x] Rol/firma matrisi ilk genisletme: IF/DOF olusturma ve duzenleme
  izinleri ayristirildi; goruntuleyici ve kisi bazli izin redleri, atanmis
  personel/yetkili yonetici akisi, Aksiyon/IF/DOF/Dokuman yabanci firma
  detay-degisiklik-onay-indirme URL'leri ve rapor firma kapsami test edildi.
  Kanit: `tests/test_security_role_operation_matrix.py`. Bu, ustteki tam
  matris maddesini kapatmaz.
- [x] IF/DOF dosya indirme ilk dilimi (canli `6179708`): acilis eki firma metaverisi,
  beklenen firma/klasor yolu ve baska IF kaydinin ayni dosyaya referansi
  denetleniyor; kapanis kaniti da ayni yol/sahiplik sinirina baglandi.
  Eski duz-kok `dof-opening-<uuid>` dosyalari sinirli bicimde korunuyor;
  genel basename fallback'i IF indirmesinde kullanilmiyor. Yanlis veya
  yinelenmis dosya metaverisi IF silinince 409 verir; kayit ve dosya korunur. Kanit:
  `tests/test_dof_file_ownership.py`. Kalici manifest ve yetim dosyanin
  tarihsel sahipligi henuz kanitlanmadi; tam dosya matrisi acik.
- [x] IF/DOF silme dosya/DB tutarliligi ikinci dilim (canli `f64629f`): dosya temizligi
  DB commit'inden sonra yapilir; commit hatasinda kayit ve dosyalar korunur.
  Bekleyen temizlik isleri firma, IF, yol, boyut ve SHA-256 ile kalici olarak
  tutulur; `flask cleanup-dof-files` dogrulayarak yeniden dener. Eksik veya
  degismis dosyada is kapanmaz. Kanit: `tests/test_dof_file_ownership.py`,
  `tests/test_dof_file_cleanup_migration.py`. Paylasimli dosya sistemi yazma
  yetkisi olan baska surecle hash/silme yarisi ve tarihsel yetim dosyalar
  ayri inceleme olarak aciktir.
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
- [x] Bu release sonrasinda sadece dusuk etkili saglik, TLS, log ve HTTP
  smoke kontrolleri yapildi. Canli yuk/siza testi ayri onaya baglidir.

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
- 27 Ekim ilk release: `354443a` canliya alindi. Canli tam yedek 204 upload
  ile dogrulandi, geri yukleme dry-run basarili, sunucu disi SHA-256 eslesti;
  migration head `202610260002`, tenant-health ve iki HTTPS giris smoke testi
  basarili. Servis ve iki zamanlayici aktif, yeni servis hata logu yok.
- Sonraki adim: Aksiyonlar rol/firma matrisi ilk dilimi yerelde calisiliyor.
  Tam matris ve bagimsiz manuel siza testi acik kalir; ilk release'in
  tamamlanmasi bunlari kapatmaz.
- Aksiyonlar ilk dilim QA: Aksiyonlar, ISG, is akisi guvenligi ve tenant
  paketinde 123 test gecti. Eski ISG rol testinde firmaya bagli Super Admin
  test verisi guncel global Super Admin hiyerarsisine uyarlandi. Tum pytest
  paketi yine tamamlanmis sayilmaz.
- 27 Ekim ikinci guvenlik dilimi: aksiyon dosya yolunda kayit metadata'si
  yabanci firma dosyasina cevrilince 200 dondugu testle yeniden uretildi.
  Indirme yolu firma ve beklenen alt klasore sinirlandi; eski duz-kok yol
  ve firma kimligi olmayan kayit da 404 olur. Ayni klasordeki baska
  aksiyonun dosyasi icin red test once 200, duzeltme sonrasi 404 dondu.
  22 odakli dosya testi ve aksiyon, ISG, yukleme guvenligi, is akisi
  guvenligi, tenant paketinde 154 regresyon testi gecti. Tum pytest paketi
  ayrica degerlendirilecek.
- 27 Ekim ikinci release: `1fe5141` canliya alindi. 204 upload iceren tam
  yedek `backup-verify` ve restore dry-run ile dogrulandi; sunucu disi
  kopyanin SHA-256 degeri eslesti. Sema degisikligi yok; migration head
  `202610260002`, `pip check` ve `tenant-health` temiz. Servis ve iki
  zamanlayici aktif; ana sayfa ve firma girisi 200, oturumsuz aksiyon
  indirme istegi 302, yeni hata logu yok. Tam pytest paketi ve yetim
  dosyalarin sahiplik tasarimi acik kalir.
- 27 Ekim ikinci tur: mevcut Odemeler/Sozlesmeler/Satin Alma modulleri
  paketi 49 testle gecti. Odeme indirmesinde metaveri yabanci firma yoluna
  degistirildiginde yeni test duzeltmeden once 200 ile kirmizi oldu; firma
  `payments` dizini sinirindan sonra 404 ile yesil oldu. Duzeltme sonrasi
  Odemeler ve tenant oturumu testleri 26 gecti; ek negatif dosya/yetki
  testleri 3 gecti. Bu turlar tam regresyon veya manuel siza testi degildir.
- Onceki `docs/WHOLE_SITE_AUDIT_2026-09-15.md` raporu tarihsel kanittir;
  bugunku surum icin dogrulama sayilmaz.
- 27 Ekim ucuncu guvenlik dilimi: yeni aksiyon ekleri firma/aksiyon/alt kayit
  kimlikli klasorlerde; indirme ve silme ayni kanonik yol sahipligini
  denetler. Dosya degisiminde eski ek ancak DB commit sonrasi temizlenir;
  rollback ve savepoint testleri eklendi. Aksiyon, ISG, upload, is akisi,
  tenant ve firsat entegrasyonu paketinde 194; bildirim politikasi,
  teslimat yarisi ve ISG entegrasyonu paketinde 91 test gecti. Son kapanis
  rollback ve silme testi guncellemesinden sonra 16 odakli test tekrar gecti.
  Tam pytest
  paketi veya bagimsiz siza testi tamamlanmis sayilmaz. Kalici manifest
  ve tombstone migration'i kalan risk olarak aciktir.
- 27 Ekim ucuncu release: `c412cfa` canliya alindi. 204 upload iceren
  `volkaportal-backup-20261027-120345.zip` yedegi dogrulandi, geri yukleme
  dry-run basarili ve sunucu disi kopyanin SHA-256 degeri eslesti. Sema
  degisikligi yok; migration head `202610260002`, `pip check` ve
  `tenant-health` temiz. Uygulama ve iki zamanlayici aktif; ana sayfa ve
  firma girisi 200, oturumsuz aksiyon indirme istegi 302, yeni servis hata
  kaydi yok. Tam regresyon ve kalici dosya sahipligi manifesti acik kalir.
- 30 Ekim dorduncu guvenlik dilimi: aksiyon dosyalarina kalici sahiplik,
  checksum ve silme tombstone'u eklendi. Dosya secilmeden yeniden kapanis
  talebi gonderildiginde mevcut kanit korunur. Aksiyon/ISG/tenant/guvenlik
  regresyonunda 357 test; ilave manifest, audit, migration ve kismi yukleme
  odakli testleri gecti. Canli DB'nin salt-okunur envanterinde dort referans
  alani `0/0/0/0`, aksiyon upload dosyasi 0. Izole canli DB kopyasinda
  `202610270001 -> 202610300001 -> 202610270001 -> 202610300001`
  provasi, SQLite butunluk ve yabanci anahtar kontrolleri temiz; aksiyon,
  kullanici ve audit kayit sayilari korundu. `9dc5c5f` canliya alindi;
  `volkaportal-backup-20261030-081100.zip` tam yedegi (204 upload) dogrulandi,
  geri yukleme dry-run ve sunucu disi kopyanin SHA-256 eslesmesi temiz.
  `pip check`, `tenant-health`, canli SQLite butunlugu ve manifest bakim
  dry-run temiz. Uygulama ve iki zamanlayici aktif; ana sayfa ve iki sirket
  girisi 200, oturumsuz aksiyon dosyasi 302, yeni servis uyari/hata logu yok.
  Canli veriye yazan kimlik dogrulanmis smoke yapilmadi.
- 30 Ekim sonraki yerel dilim: IF/DOF `if.create`, `if.edit_assigned` ve
  `if.edit_all` kisi bazli izinleri; route ve yeni kayit dugmesi buna
  baglandi. Goruntuleyici kullanicinin kendisine ait IF kaydini yetkisiz
  degistirebilmesi engellendi. `test_security_role_operation_matrix.py`
  ile rol/firma/rapor senaryolari eklendi. IF/DOF, Aksiyon, Dokuman,
  Rol Navigasyonu, Rapor Merkezi ve Tenant paketinde 123 test gecti.
  Canliya alinmadi; tam rol matrisi,
  dosya metaverisi sahipligi ve bagimsiz siza testi acik.
- Ayri regresyon bulgusu:
  `test_periodic_reporting.py::test_every_company_module_has_an_activity_report_mapping`
  mevcut
  `purchase_requests`, `payment_tracking`, `contracts`, `ohs_actions`
  eslemeleri eksik oldugu icin basarisiz. Bu guvenlik diliminde rapor
  eslemelerine dokunulmadi; raporlama backlog'unda ele alinmali.
- 30 Ekim rol/firma ilk dilim release: `330fefe` canliya alindi. Once
  `volkaportal-backup-20261030-103943.zip` tam yedegi (204 upload)
  dogrulandi, geri yukleme dry-run temiz ve sunucu disi SHA-256 eslesti.
  Fast-forward guncelleme, Python 3.12.13, `pip check`, migration head
  `202610300001` ve `tenant-health` temiz. Uygulama ve iki zamanlayici aktif;
  ana site ve sirket girisi HTTPS 200, yeni servis warning/error logu yok.
  Canli kimlik dogrulanmis yazma testi yapilmadi.
- 30 Ekim sonraki IF/DOF dosya dilimi: yabanci firma dosyasi
  metaverisinin once 200 indirme verdigi kirmizi testle kanitlandi.
  Indirme ve silme yolu beklenen firma klasorune sinirlandi; canli salt-okunur
  envanterinde 46 acilis ekinin 45'i duz-kok legacy oldugundan dar eski
  dosya kurali korundu; 45'inin adi kurala uyuyor ve dosyasi mevcut.
  Yerel IF/DOF, yukleme guvenligi, rol/firma ve tenant paketinde 60 test gecti.
  `6179708` canliya alindi: `volkaportal-backup-20261030-121406.zip`
  (204 upload) dogrulandi, dry-run temiz, sunucu disi SHA-256 eslesti.
  Fast-forward, `pip check`, migration head `202610300001`, tenant-health,
  servis/zamanlayicilar, iki HTTPS 200 ve warning log kontrolu temiz.
- 30 Ekim ikinci dilim: IF silme commit-sonrasi, kalici temizleme
  kuyrugu, SHA-256 ile retry ve `202610300002` migration eklendi. 66 ilgili
  test ve son degisiklik icin 17 odakli test gecti. Canli yedek kopyasinda
  upgrade/downgrade/upgrade ve SQLite integrity kontrolu temiz. `f64629f`
  canliya alindi: `volkaportal-backup-20261030-125407.zip` (204 upload)
  dogrulandi, dry-run temiz, sunucu disi SHA-256 eslesti. Fast-forward,
  Python 3.12.13, `pip check`, migration head `202610300002`, tenant-health,
  temizlik CLI'si `0 bekleyen`, servis/zamanlayicilar, iki HTTPS 200 ve
  warning log kontrolu temiz. Canli kimlik dogrulanmis IF silme testi
  yapilmadi; eksik/degisen dosya isleri fail-closed bekler ve operasyonel
  inceleme gerektirir.

# VolkaPortal Site Denetimi

Tarih: 2026-09-15. Yerel test verileri kullanildi; canli sunucu ve kullanici
veritabani degistirilmedi. Bu rapor sifir hata veya eksiksiz penetrasyon testi
garantisi degildir.

## Kapsam ve Kanitlar

- Uygulama haritasi: 303 route, GET kabul eden 194, POST kabul eden 197 route.
  GET ve POST sayilari ortak route'lar nedeniyle toplanamaz.
- Anonim erisim taramasi: dahili GET ve POST endpoint'leri basarili islem/ekran
  cevabi vermemeli. Bu kontrol tek basina her rolun yetkisini kanitlamaz.
- Sunucu tarafinda uretilen POST formlarinda CSRF token kontrolu.
- Alti rol icin sidebar HTML'sindeki dahili baglantilara GET kontrolu:
  Super Admin, Yonetim Temsilcisi, Yonetim, Departman Yoneticisi, Personel,
  Goruntuleyici. HTML parser CSS ile gizlenen baglantilari da gorebilir;
  beklenen tum menu ogelerinin mevcut oldugunu kanitlamaz.
- Onceki Playwright turu: 46 menu URL'si x 3 viewport = 138 navigasyon;
  1440x900 masaustu, 768x1024 tablet, 390x844 mobil.
  Bu turda HTTP 200, sayfa seviyesinde yatay tasma, bozuk metin taramasi ve
  JavaScript hatalari kontrol edildi. Tum kayit/detay senaryolari degil,
  izole test sirketinin menu ekranlari kontrol edildi.
- Mobil sidebar: alt menuler acildi, nav sonuna kaydirildi; bildirimler,
  gorevler ve cikis ulasilabilir bulundu. Bu bir FPS/yuk testi degildir.
- Temiz migration kurulumu: 88 model tablosunun ve tum model kolonlarinin
  seed olmadan mevcut oldugu dogrulandi.
- Onceden mevcut runtime tablolariyla migration, tekrar upgrade, veri
  koruma, indeksler ve isimsiz eski UNIQUE constraint senaryolari eklendi.
- Uretim requirements taramasi: pip-audit bilinen zafiyet bulmadi.
  Bu sonuc sifir guvenlik acigi anlamina gelmez.
- Tam test paketi anlik goruntusu: 317 passed, 181 warnings (14:50).
  Sonraki duzeltmeler bu tam paket kosusuna dahil degildir; etkilenen moduller
  ayrica 46 passed, 56 warnings ile tekrar kontrol edildi.
- Son migration ve tenant kontrolleri: 28 passed (36.55 saniye).
- Son oneri ekranlari: ana liste ve Onerilerim x uc viewport = 6 navigasyon;
  HTTP 200, sayfa seviyesinde yatay tasma 0, JavaScript hatasi 0.
  Mobil bos liste mesaji ekran goruntusunde ayrica incelendi.
- pip check: bagimlilik uyumsuzlugu bulunmadi. git diff --check temiz.

## Duzeltilenler

- Dokuman yuklemede baska sirketin kategori ID'si reddediliyor.
- Proxy IP basliklari yalnizca tanimli guvenilir proxy'den kabul ediliyor;
  login, audit ve musteri portalinda ortak IP kurali kullaniliyor.
- Kullanici bazli login kilidi sirket kapsaminda tutuluyor. Ad-soyad ve
  kullanici adi ayni hesabin sayacina gider; IP korumasi ayridir.
- Pasiflestirilen kullanicinin mevcut oturumu sonraki istekte temizleniyor.
- Sirket kullanicisinin adi superadmin olsa bile global admin araclari acilmiyor.
- Yeni parola/guncelleme varsayilani 10-128 karakter; ust sinir ve hatali
  min/max ayarlarinin celiskisi kontrol altinda.
- Uretim seed bilinen parolali demo hesap/sirket olusturmuyor veya mevcut
  admin hesabini yeniden aktiflestirmiyor. Ilk admin gizli parola istemiyle
  create-superadmin komutundan olusturuluyor.
- Gunicorn import sirasinda create_all/seed kaldirildi. Dogrudan calistirmada
  otomatik bootstrap yalnizca development icin; production debug acilmiyor.
- Runtime-only 23 tablo ve ek kolonlar frozen, additive migration'a alindi.
  Mevcut tablo/kolonlar silinmez. Downgrade veri kaybi riski nedeniyle engelli;
  geri donus dogrulanmis yedekten yapilmali.
- Tenant-health sabit/eski head yerine gercek Alembic head'lerini okuyor.
  Ornek 001/000 sirketlerinin bulunmamasi hata sayilmiyor; guvenli ilk
  kurulum demo sirket gerektirmiyor. Global admin sirket disi kapsamda aranir.
- Oneri duzenleme/silmede sahiplik, yonetici ve durum kontrolleri eklendi;
  puanlanmis kaydin tanimi degistirilemiyor. UI ayni kurallari kullaniyor.
- Oneri degerlendirmesi kullanici ID'siyle benzersiz; ayni isimli kisiler
  birbirinin puanini ezmiyor ve isim degisikligi ek puan olusturmuyor.
- Degerlendirme bekliyor/yapti ozeti isim yerine kullanici ID'sinden hesaplanir.
- Onay bekleyen kayit sahibine Onerilerim gorunumunden ulasilabilir;
  ana listede onay bekleyen diger kullanicilarin kayitlari gizli kalir.
- Oneri bos liste mesaji genis tablonun disina alindi; mobilde kaybolmuyor.
- Revizyon talebinin tekrar onayi 409 doner; dosya isleminden once kosullu
  satir guncellemesiyle eszamanli onay icin sahiplenme kontrolu eklendi.
  Cok-worker stres testi henuz yapilmadi.
- Kapanis bildirimi sabit oguzhan hesabina degil sirketin gercek onay
  yetkililerine gidiyor; mesaj da kisi adina bagli degil.
- Hatali yeni ek yuklemesi mevcut aksiyon/oneri ekini silmiyor.
- IT gibi kisa departmanlar Kalite gibi ilgisiz basliklarla eslesmiyor.
- Harici referrer'a CSRF hata yonlendirmesi engellendi.
- nosniff, frame/base/object/form korumalari, referrer/permissions politikasi,
  production HSTS ve hassas HTML/JSON/dosyalarda no-store eklendi.
- Yinelenen bildirim filtresi kaldirildi; temel user lookup session.get oldu.
- Zafiyetli dogrudan bagimliliklar guncellendi; gelistirme araclari ayri
  requirements-dev.txt dosyasina alindi. Python 3.10+ zorunlu.

## Kalan Kararlar ve Riskler

- Oneri tamamlama karari verildi: bos kriter eksik degerlendirmedir.
  Yerelde tum aktif kriterlerde 1-10 puan olmadan kisi tamamlamis sayilmiyor.
  Kismi kayit saklanir, bos secim eski kisisel puani siler, gorev acik kalir.
  Yeni aktif kriter onceki tamamlanmayi yeniden eksik yapar. Workflow ve
  Gorevlerim regresyonu: 15 passed, 28 warnings. Kod sonrasinda
  1cd6e45 surumuyle canliya dagitildi; LIVE_RELEASE_2026-09-15.md kanitlari.
- Bazi route'lar runtime schema kontrol/onarimlarini halen cagiriyor.
  Migration eksiklerini kapatmak bunlari tamamen kaldirmis sayilmaz.
  Production DDL'nin tum endpoint'lerden ayrilmasi ayri kontrollu calisma olmali.
- CSP henuz nonce tabanli script-src/default-src politikasi degil.
- Dahili yuklemelerde kapsamli imza/zararli yazilim taramasi ve dosya/DB
  islemlerinin tum hata noktalarinda atomikligi ayrica guclendirilmeli.
- Genel backup validator'da eksiksiz checksum kapsami, duplicate ZIP yolu,
  bozuk JSON turleri ve kaynak limitleri guclendirilmeli. Bu islemde uretilen
  gercek yedek bagimsiz ek kontrolle tam kapsami dahil dogrulandi;
  bu sonuc genel validator'in tum bozuk paketleri reddettigini kanitlamaz.
- Eski, daha once seed edilmis bilinen parolali hesaplar otomatik silinmedi;
  canlida hesap envanteri, parola degisimi ve gereksiz hesaplari pasiflestirme gerekli.
- Yeni migration eski ayni-kullanici/parametre duplicate puan kaydi bulursa
  veri silmeden durur. Canli veride preflight/duzeltme incelemesi gerekir.
- Gercek e-posta teslimi, DNS/TLS, gercek musteri verisi, yuk/eszamanlilik,
  tum rol x tum durum x tum POST matrisi ve butun kayitlarla mobil ekranlar
  bu yerel turla tamamen kanitlanmadi.
- pytest uyarilari agirlikla legacy Query.get ve utcnow kullanimlari;
  ilgisiz toplu refactor yapilmadi.

## Dagitim Kapisi

Ilk denetim turunda canliya alma yapilmadi. Sonraki kullanici onayiyla yalnizca
Python runtime ve yedekleme gereklilikleri canlida tamamlandi. Daha sonraki
acik canliya alma onayiyla uygulama kodu ve migration'lar da dagitildi.
Ayrinti: LIVE_RUNTIME_2026-09-15.md ve LIVE_RELEASE_2026-09-15.md.
Kod dagitimindan once Python/venv 3.10+ dogrulanmali, tam yedek
alinip dogrulanmali, dependencies kurulup pip check yapilmali, servis dururken
migration ve tenant-health calistirilmali. Her komutun cikis kodu kontrol
edilmeli; hata olursa servisi baslatmadan neden cozulmeli.
Komutlar: docs/BACKUP_RESTORE.md. Tum site tamamlandi checklist'i isaretlenmedi.

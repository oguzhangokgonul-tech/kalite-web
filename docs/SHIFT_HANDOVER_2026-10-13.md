# Vardiya Devir Teslim Notlari

## Kapsam

- Lider onayi: Vardiya devir teslim notlarindan devam edilmesi ve dogrulama sonunda canliya alinmasi.
- Sol menu ve Mobil Merkez: `/vardiya-devir-teslimi`.
- Taslak olusturma/duzenleme, gonderim, atanmis kullanicinin teslim almasi, gerekceli iptal ve arsiv.
- Vardiya tarihi, vardiya, departman, alan, baslik; ozet, bekleyen isler, guvenlik, kalite ve ekipman notlari.
- Devreden oturumdan alinir. Baska kullanici adina teslim alma yapilamaz.
- Gonderilen icerik degismez; arsiv fiziksel silme degildir. Eszamanli degisiklikler version_id ile korunur.
- Uygulama ici bildirim, Gorevlerim ve Rapor Merkezi baglantilari. Yeni gunluk e-posta uretilmez.
- Aylik, 3 aylik, 6 aylik ve yillik Excel; ayni firma ve kisi gorunurlugu korunur.
- Alti ayri izin: view, view_all, create, receive, manage, export. Sadece goruntuleyici islem yapamaz.
- Kritik degisiklikler audit loga ayni transaction icinde yazilir.

## Ertelenen Maddeler

12 Ekim'deki canli durum 78/140 aktif maddeydi. Asagidaki bes acik madde, tamamlandi sayilmadan ertelendi:

1. Yillik yonetim programi ve toplanti takvimi.
2. Ic / dis iletisim plani.
3. Is surekliligi ve acil durum aksiyon plani.
4. Uretim planlama modulu.
5. Is emri ve operasyon takip modulu.

Onceki e-imza ve SSO/MFA ertelemeleri korunur. Toplam ertelenen madde 7, aktif katalog 135 olur.
Vardiya maddesi sadece yayin dogrulamasindan sonra tek anahtarli ve auditli release komutuyla isaretlenir.
Sonraki aktif madde: Gunluk uretim raporu.

## Dogrulama ve Yayin

- Planlamaci/ISO-is akisi incelemesi alindi. Onceki kodcu, QA ve release ajanlarinin yarim kalan ciktilari incelendi.
- Ilk UI kontrolde 390/768/1440 pikselde liste, form ve detay: 9/9 HTTP 200, tasma ve JavaScript hatasi yok.
- Izole mobil tarayicida CSRF etkin gonderme ve teslim alma akisi basarili.
- Onceki canli yedegin kopyasinda migration upgrade/downgrade/upgrade: 165 eski tablonun verisi korundu.
- Graphify yerel AST analizi guncellendi; harita, gecici dosyalar, loglar ve yedekler commit/deploy edilmez.
- Son kontroller: 68 entegrasyon/rapor/PWA/checklist testi ve 34 gorev/tenant/audit/zimmet regresyon testi basarili.
- Bagimsiz QA: modul, migration ve release icin 82 test; ayrica 3 entegrasyon testi basarili. Yayin engeli bulunmadi.
- Bagimsiz QA ayrica bildirim hatasinda rollback, pasif devreden ve hareket raporu yetkilerini dogruladi.
- Test ortami Python 3.12.13; Python 3.10 uzerinde ayri calistirma yapilmadi.
- Yayin oncesi guncel test, taze yedek, sunucu disi checksum ve migration provasi gereklidir.
- Yayinda migration: `202610120001 -> 202610120002`.
- Release configure yalniz ilgili izinleri ve eksik modul secimini ekler; mevcut kapali modul secimleri ve ozel yetkiler korunur.
- Aktif custom/production_plus firmalarda eksik modul acilir; iso_core firmalar icin kapali kalir.

## Geri Donus

Yeni kayit varsa migration downgrade tabloyu siler; uretimde uygulanmaz. Once modul kapatilir,
servis durumu incelenir ve veri koruyan duzeltme commit'i tercih edilir. Yedekten geri yukleme
ancak Lider karari ve yedek sonrasi olusan kayitlarin korunmasi planlandiktan sonra yapilir.
Gecis oncesi uygulama hash'i: `eb969853fe6da5679f840e0932ccbd8e44ddf53b`.

## Sinirlar

Teslim alma, notta belirtilen bekleyen islerin tamamlandigi anlamina gelmez. Notlar DOF, bakim veya
olay kayitlarinin yerine gecmez. Dosya eki ve vardiya personel planlamasi bu ilk surumun kapsaminda degildir.

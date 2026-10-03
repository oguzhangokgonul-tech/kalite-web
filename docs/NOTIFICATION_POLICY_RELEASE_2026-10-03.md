# Bildirim Politikası Yayın Kaydı

## Durum

Yayın öncesi doğrulama sürüyor. Bu kayıt tek başına canlıya alındığı anlamına gelmez.
Ürün sahibi temel politika için uygulama ve yayın onayı verdi. Saat dışı kritik
e-posta istisnası açılmadı.

## Kullanım

Bildirimler > Bildirim Ayarları:

- Her kullanıcı: önemli bildirimler + haftalık özet, yalnızca haftalık özet,
  yalnızca site içi tercihlerinden birini seçebilir.
- Yönetim Temsilcisi ve Süper Admin: mevcut şirketin e-postasını, haftalık gününü,
  her kaynak için mail/haftalık özet seçimini ve termin öncesi günleri ayarlayabilir.
- Varsayılan: pazartesi özeti ve belirli termin eşikleri. Eski gecikmeler her gün
  gönderilmez. Yeni olaylar ve farklı terminler farklı günlerde mail oluşturabilir.
- Planlı gönderim Europe/Istanbul 08:30; zamanlayıcı toleransı 10 dakika.
  Bir şirket/kullanıcı/gün için en fazla bir paket; başka saatte `--force` göndermez.
- Şifre sıfırlama ve müşteri doğrulama/takip gibi işlem mailleri bu tercihten ayrıdır.

## Uygulama

Kalıcı olay ve günlük gönderim tabloları eklenir; mevcut iş kayıtları değiştirilmez.
Olaylar iş işlemiyle birlikte commit edilir. SMTP kabul edilmeden bildirim
gönderildi sayılmaz. SMTP kabulü, posta kutusuna ulaşma veya okunma kanıtı değildir.
Gönderimden önce güncel şirket, kullanıcı, modül, yetki, sahiplik ve açık iş kontrol edilir.
İşin aynı sabahki olay ve termin kayıtları birleştirilir.

Aksiyon, alt aksiyon, DÖF, doküman revizyonu ve müşteri portalı önemli olayları
kuyruk kullanır. Araç sayfası açılınca mail gönderilmez. Mevcut merkezi termin
kaynakları ortak politikayı kullanır. Ek kaynaklar: araç tarihleri, öneri onay ve
bekleyen değerlendiriciler, güncel doküman okuma-onay, toplantı/karar, betonun
bekleyen ölçümü, etkinlik kontrolü, süreç/FMEA/değişiklik/sapma/olay/Kaizen,
A3/8D adımı, iç talep, iş izni ve doğrulanmış müşteri geri bildirimi.

## Kapsam Sınırları

- Araştırma bütün gelecek modül özelliklerinin teslim listesi değildir. 7/14 gün
  yönetici yükseltmesi, kritik eşik kuralları, aylık yönetici KPI özeti ve çalışma
  takvimi henüz uygulanmadı. Sorumlu-yönetici eşleştirmesi ürün kararı gerektirir.
- Saha kontrol/5S, resmî yazışma ve ekipman kabulü için yeni olay kaynakları bu
  sürümde eklenmedi. Mevcut site içi akışlar korunur; bağlı aksiyonlar ortak politikadadır.
- Açık bir sorumlu alanı olmayan modüllerde oluşturucu sorumlu varsayılmaz;
  mevcut modül işlem yetkilileri kullanılır. Ayrı sahiplik modeli sonraki iştir.
- SMTP sonucu belirsiz paket otomatik tekrar edilmez. Kesin başarısız olay en çok
  üç denemeye alınır, aynı gün yeniden gönderilmez. Ertesi gün hâlâ açık olmalıdır.
- SQL FK'ları tek başına şirket eşitliğini zorlamaz; uygulama kontrolü ve tenant
  regresyonları zorunludur. Doğrudan SQL ile sahiplik değiştirme desteklenmez.
- Yedi günlük gerçek önizleme, iki haftalık pilot ve hacim azalması ölçümü tamamlanmadı.
  %70 azalma veya kusursuz teslim garantisi verilmez.

## Operasyon

Servisin gerçek ortam değişkenleri ve `venv-py312` ile:

```bash
python -m flask --app app:create_app preview-notifications --company-id 1 --on-date 2026-10-05
python -m flask --app app:create_app notification-delivery-status --company-id 1
```

Önizleme SMTP kullanmaz, veri yazmaz; tarih tabanlı adayları sayar, bekleyen olay
kuyruğunun tam teslim tahmini değildir. Tanılama içerik/adres değil durum, paket
kimliği ve hata kodunu gösterir. `accepted`: SMTP kabulü; `failed`: kesin başarısız;
`uncertain`: insan kontrolü gerekli; `cancelled`: gönderim uygun değil.
Eski `claimed/sending` paketler sonraki çalışmada `uncertain` olarak işaretlenir.

Belirsiz pakette önce SMTP sağlayıcı logunu paket zamanı ve yetkili alıcı kaydıyla
karşılaştırın. Kuyruğu topluca `pending` yapmayın, paket/tekillik satırlarını silmeyin.
Alan adı yoksa bozuk URL yerine paket `no_current_items_or_domain` koduyla iptal edilir.

## Yayın ve Geri Dönüş

Yeni migration: `202610020002`, önceki: `202610020001`.
Temiz hedef diff, bağımsız QA, başarılı regresyon, güncel tam yedek,
checksum + restore dry-run, sunucu dışı kopya ve kopya üzerinde migration provası gerekir.
Web uygulaması ve diğer DB/upload yazarları tutarlı yedek ve yükseltme sırasında durdurulur.
Yayın sonrası servis, tenant sağlık, giriş sayfaları ve göndermesiz önizleme kontrol edilir.

Geri dönüşte önce mail zamanlayıcısını durdurun ve operasyonel maili kapatın.
Kod-only geri dönüş kullanın; yeni kuyruk tablolarını koruyun. Eski kod günlük/anlık
gönderimi geri getirebileceği için maili otomatik yeniden açmayın. Canlıda downgrade
çalıştırmayın: bu, olayları ve tekrar korumasını siler. Veri restore'u ayrıca lider onayı ister.

## Kanıtlar

- Önceki canlı yedek kopyasında 9 aşama, 29 kısıt kontrolü, 4 temiz şema karşılaştırması.
  153 tablo / 13.796 satır korundu. Yedek SHA256:
  `09c9a7027044317c01a60d0a34ad758c04b8f9acb27e5333ba6f1b6be84220dc`.
- Genişletilmiş bildirim/tercih/portal/migration paketi: 215 test geçti.
- İş akışı/tenant regresyonu: 130 test geçti; eski kaldırılmış mail fonksiyonuna
  bağlı 3 test taklidi, gerçek SMTP gönderim sınırını kontrol edecek şekilde düzeltildi.
- Son toplantı aksiyonu ve gönderim yarış/yönlendirme paketi: 73 test geçti.
- Bağımsız son QA: 69 test geçti; önceki 3 yönlendirme hatası giderildi,
  incelenen kapsam için yayın engelleyici bulgu kalmadığı bildirildi.
- Playwright 390/768/1440 px: Yönetim Temsilcisi ve Personel için toplam 6 senaryo;
  tercih/şirket formu CSRF ile kaydedildi, taşma ve tarayıcı JS hatası bulunmadı.
- Canlı ön kontrol: `9453a9c`, uygulama aktif, zamanlayıcı 08:30 Europe/Istanbul.
- Güncel yedek, yayın commit'i ve canlı sonrası doğrulama: bekliyor.

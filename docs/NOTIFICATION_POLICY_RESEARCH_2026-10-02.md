# VolkaPortal Bildirim Politikası Araştırması

Tarih: 02.10.2026
Durum: Temel politika ürün sahibi tarafından onaylandı. Uygulama ve yayın doğrulaması sürüyor; saat dışı kritik e-posta istisnası kapalı. Güncel uygulama kapsamı ve kanıtlar: `NOTIFICATION_POLICY_RELEASE_2026-10-03.md`.

## 1. Karar özeti

Ana kanal site içindeki Bildirimler ve Görevlerim olmalı. E-posta; gerçekten işlem gerektiren atama/onay, belirli termin eşikleri ve haftalık özet için kullanılmalı. Değişmeyen bir kayda her gün yeniden e-posta gönderilmemeli.

Önerilen varsayılan: Pazartesi 08:30 haftalık özet + aşağıdaki belirli tarih/olay uyarıları. Saat dilimi Europe/Istanbul. Bu model, her gün aynı kayıtların gönderilmesini kaldırır; farklı günlerde yeni görev veya önemli termin varsa o günlerde yine e-posta olabilir. Haftada kesinlikle tek e-posta isteyen kullanıcı için ayrı bir tercih gerekir; kritik uyarılar bunun dışında ayrıca kararlaştırılmalıdır.

Bu belge bir mevzuat uygunluk değerlendirmesi değildir. Aşağıdaki gün aralıkları rakiplerin ortak zorunluluğu veya ISO şartı olarak sunulmuyor; VolkaPortal için önerilen ürün varsayılanlarıdır.

## 2. Rakiplerde doğrulanan yaklaşımlar

| Ürün | Resmî kaynaktaki davranış | VolkaPortal için çıkarım |
| --- | --- | --- |
| QDMS | Cihaz ön bildiriminde e-posta alacak roller seçiliyor; işlem tipinde tanımlı ön bildirim süresi, yoksa modül parametresi kullanılıyor. | Her modülün aynı sıklıkta ve herkese mail göndermesi gerekmez. |
| QDMS BGYS kılavuzu | Onay akışında ilk, ikinci ve son hatırlatma günleri ayrı tanımlanabiliyor. Bu, ilgili modül kılavuzunun davranışıdır; tüm QDMS kurulumlarına genellenmemeli. | Onay bekleyen işlerde sınırlı sayıda, aşamalı hatırlatma. |
| Diligent One | Tekrarlı hatırlatma günlük, haftalık veya aylık seçilebiliyor; varsayılan haftalık. Termin öncesi özel günler tanımlanabiliyor. Kapanan veya ilgili kişiden alınan iş için hatırlatma duruyor. | Haftalık tekrar + termin eşikleri + güncel sahiplik kontrolü. |
| Asana | Geciken görevler haftalık hatırlatılıyor; günlük özet gecikmiş görevleri içermiyor. Yakın zamanlı bazı güncellemeler tek e-postada birleştiriliyor. | Eski gecikmeleri her gün yeniden göndermek yerine haftalık özet. |
| Jira | Uygulama içi ve e-posta tercihleri ayrılabiliyor. Küçük değişiklikler birleştiriliyor; bazı önemli olaylar anında gönderiliyor. | Kanal ayrımı, e-posta birleştirme, önem derecesi ayrımı. |
| Oneri.io | Öneri paydaşlarına otomatik e-posta, SMS ve mobil bildirim sunduğunu açıklıyor. Açık ürün sayfasında gün bazında tekrar takvimi açıklanmıyor. | Paydaş odaklı bildirim örnek alınabilir; bilinmeyen bir tekrar sıklığı rakibe atfedilmemeli. |

Kaynaklar:

- [QDMS cihaz ön bildirim ayarları](https://docs.bimser.net/docs/QDMS/frequently_asked_questions/i%CC%87%C5%9F_emirleri_on_bildirim_ayarlari/)
- [QDMS BGYS kılavuzu: onay ve hatırlatma alanları](https://docs.bimser.net/docs/Legacy/QDMS/user_manuels/BGYS)
- [Diligent One e-posta ve tekrar ayarları](https://help.diligentoneplatform.com/helpdocs/d1p/en-us/Content/projects/getting_started/email_notifications.html)
- [Asana e-posta bildirimleri](https://help.asana.com/s/article/email-notifications?language=nl-NL)
- [Jira kişisel bildirim tercihleri](https://support.atlassian.com/jira-software-cloud/docs/manage-your-jira-personal-settings/)
- [Oneri.io öneri sistemi](https://oneri.io/oneri-sistemi/)

Not: Bazı Bimser ve Asana sayfaları doğrudan açıldığında hata verdi; ilgili resmî sayfaların arama motorunda sunulan içerikleri de kullanıldı. Müşteriye kapalı ayarlar ve gerçek kurulumların gönderim kayıtları incelenmedi.

## 3. Mevcut kodda günlük tekrarın nedeni

- `app/reminders.py:130`: `_date_in_window`, hedef tarihe kalan günün eşikten küçük/eşit olmasını kontrol ediyor. Bu koşul gecikmiş kayıtlar için sonraki günlerde de doğru kalıyor.
- `app/reminders.py:145`: `_source_key`, çalışma tarihini anahtara ekliyor. Aynı kayıt ertesi gün farklı anahtar kazanıyor.
- `app/reminders.py:150`: `_send_record_reminders`, oluşturduğu site bildiriminin ardından aynı kullanıcıya e-posta göndermeyi deniyor. İki kanalın politikaları bu akışta ayrılmamış.
- `app/reminders.py:210`: aksiyon sorgusu, termin eşiğinin içindeki tamamlanmamış kayıtları seçiyor. Gecikince belirli yetkilere sahip kullanıcılar da alıcılara ekleniyor; görev sahibi dışında geniş bir alıcı grubu oluşabiliyor.
- `app/reminders.py:324`: bekleyen doküman revizyonları, belirli hatırlatma günleri yerine her çalıştırmada ele alınıyor.
- `app/reminders.py:1144`: çoğu modül için varsayılan ön uyarı penceresi 7 gün; kalibrasyon/tedarikçi için 30 gün. Bunlar tekrar aralığı değil, seçime başlama eşikleri.
- `app/reminders.py:1192`: şirket başına aynı gün tekrar çalıştırmayı engelleyen kontrol var. Bu, ertesi günkü tekrarı engellemiyor.
- `app/routes.py:10377`: aksiyon olaylarının ayrı e-posta yolu var. Yalnızca zamanlayıcıyı haftalığa çevirmek bütün e-postaları denetlemez.
- `app/routes.py:9812`: araç hatırlatmaları ayrı bir yoldan, gönderildi alanlarıyla takip ediliyor. Araç ekranının veri hazırlığında gönderim çağrılıyor; merkezî zamanlama kapsamına alınmalı.

Bu bulgular yerel kaynak incelemesine dayanıyor. Canlı SMTP kayıtlarından günlük hacim ölçülmedi; her modülün şu anda her gün mail attığı iddia edilmiyor.

## 4. Ortak kurallar

1. Site bildirimi ilgili olayda hemen oluşur. Aynı açık iş için her gün yeni bildirim satırı üretilmez; mevcut işin güncel gecikmesi gösterilir. Anlamlı durum değişiklikleri geçmişte korunur.
2. Rutin e-posta özeti pazartesi 08:30'da, yalnızca içerik varsa gönderilir. Kişi yalnızca kendi işleri ve yetkili olduğu kapsamı görür.
3. Yeni sorumluluk, onay isteği, iade veya önemli termin değişikliği, sıradaki 08:30 gönderimine bir kez alınır. Sıradan açıklama/ek/düzeltme e-postaya dönüşmez.
4. Kişi ve şirket başına aynı 08:30 çalışmasındaki haftalık özet, olaylar ve terminler tek e-postada birleştirilir. Aynı iş tek satır olur; en önemli neden öne çıkarılır.
5. Normal gecikmeler yalnızca haftalık özette tekrar eder. Gecikmenin 7. gününde doğrudan yöneticiye, 14. gününde süreç sahibine birer yükseltme önerilir. Bunlar herkesin CC'ye eklenmesi anlamına gelmez.
6. Kritik durumlar için aşağıdaki özel politika ortak gecikme kuralının önüne geçer. Geçmiş tarihli kayıtta politika açılırsa kaçırılmış bütün eşikler topluca gönderilmez; mevcut en önemli aşama tek bildirim olur.
7. Tamamlanan, iptal edilen, arşivlenen veya artık kullanıcıya ait olmayan işler gönderim anında yeniden kontrol edilerek kuyruktan çıkarılır. İş tamamlanıp kapanış onayı bekliyorsa hatırlatma sorumludan onaycıya geçer.
8. Bildirimin okunması işin tamamlandığı anlamına gelmez. E-posta teslimi de doküman okuma/onay kanıtı yerine geçmez.
9. Toplantı kararı, risk veya DÖF üzerinden açılan aynı aksiyon iki modülden ayrı ayrı hatırlatılmaz. Farklı sorumlusu/termini olan bağımsız görevler korunur.
10. Şirketler arası özet birleştirilmez. Bağlantı bildirimin şirketinin doğrulanmış HTTPS alan adına gider. Eksik/`None` alan adı varsa bozuk linkli mail yerine hata kaydı ve yetkiliye site uyarısı üretilir.
11. Varsayılan eşikler takvim günüdür. Fabrika vardiyası nedeniyle hafta sonları körlemesine atlanmaz. Şirket çalışma takvimi eklenirse normal uyarı önceki çalışma gününe alınabilir; gerçek termin değişmez.
12. Her gün çalışan kontrol servisi kalabilir; her gün kontrol etmek, her gün mail göndermek değildir. Gönderilecek olay yoksa e-posta gönderilmez.

## 5. Modül bazında önerilen politika

T = ilgili işin son tarihi. T-7 = 7 gün önce, T+7 = 7 gün gecikme. Bütün satırlarda site bildirimi gerektiği anda görünür. Aşağıdaki e-postalar, ayrıca belirtilmedikçe 08:30 paketine girer. Haftalık tekrar pazartesi özetidir; her kayıt için ayrı mail değildir.

| Modül / süreç | Yalnızca site içinde kalanlar | E-postaya alınan olay / eşik | Gecikmede davranış ve alıcı |
| --- | --- | --- | --- |
| Aksiyon / alt aksiyon | Yorum, dosya, rutin ilerleme | Atama ve onay isteği bir kez; T-7, T | Sorumluya haftalık; T+7 yönetici, T+14 süreç sahibi |
| İF / DÖF / CAPA | Rutin kanıt ve açıklama değişiklikleri | Sorumlu/onaycı ataması; faaliyet ve etkinlik kontrolü için ayrı T-7, T | Normalde haftalık; kritik sınıfı varsa kritik politika |
| Doküman revizyon onayı | Taslak ve ara düzenleme | Onaycıya ilk istek, sonuçlanmazsa 3. ve 7. gün | Sonra yalnızca haftalık; talep sahibine nihai sonuç bir kez |
| Doküman yayını / okuma-onay | Genel yayın duyurusu; kullanıcıyla ilgisiz revizyon | Zorunlu okuyucuya atama, T-3, T | Yalnızca okumayan/onaylamayan kişiye haftalık |
| İç denetim | Hazırlık notları ve dosyalar | Denetçi/denetlenen sorumluya plan kesinleşince, T-7, T-1 | Açık cevap/bulgu işleri haftalık; kapanan denetim için eski plan maili yok |
| Kalibrasyon | Cihaz kartı düzenlemesi | Cihaz sorumlusuna T-30, T-7, T; yeni süre aşımında kalite sorumlusuna bir kez | Açık kayıt haftalık; site üzerinde süre aşımı sürekli görünür |
| Bakım | Rutin bakım notu, tamamlanan işin ayrıntısı | Atama, T-7, T; kritik arıza kritik politika | Bakım sorumlusu; normal açık iş haftalık |
| Araç sigorta / muayene | Yakıt, masraf, rutin araç değişikliği | Araç/bakım sorumlusuna T-30, T-7, T | Süre aşımı yetkiliye bir kez, sonra haftalık |
| Beton deneyleri | Normal sonuç girişi/düzeltmesi | Eksik ölçümün gerçek ölçüm tarihinde laboratuvar sorumlusuna bir kez | Ertesi gün hâlâ eksikse bir kez yükseltme; sonra haftalık. 2/7/28 günlük ölçümler ayrı işlerdir |
| Metilen / su emme / elek / demir çekme | Normal deney kayıtları ve sonuçlar | Planlı iş varsa termin günü; tanımlı kabul kriterine göre uygunsuz sonuç bir kez | İlgili laboratuvar/kalite sorumlusu. Kabul kriteri olmayan veriden otomatik uygunsuzluk çıkarılmaz |
| Öneri ön onayı | Rutin notlar | Yönetim temsilcisine ilk istek; bekliyorsa 3. ve 7. gün | Sonra haftalık; karar öneri sahibine bir kez |
| Öneri değerlendirmesi | Başkalarının değerlendirme hareketleri | Seçili değerlendiriciye bir kez atama; tamamlamadıysa 7 gün sonra | Yalnızca bekleyen kişiye haftalık; bireysel puanlar mailde paylaşılmaz |
| Müşteri şikayeti | İç yorum/kanıtlar | İç sorumluya atama; yanıt termininden 1 gün önce ve termin günü | Normalde haftalık; kritik şikayet kritik politika. Müşteriye sadece kendisine açık cevap/sonuç |
| Müşteri portalı | İç ekip yazışmaları | Kayıt alındı, müşteriye açık yanıt, sonuç birer kez | Doğrulama bağlantısı talep üzerine; müşteri hiçbir iç özete eklenmez |
| Risk / fırsat / FMEA | Rutin analiz ve puan değişiklikleri | Gözden geçirme T-7, T; kritik eşik ilk kez aşılırsa bir kez | Risk sorumlusu; normal açık değerlendirme haftalık, bağlı aksiyon ayrıca çoğaltılmaz |
| İSG riskleri / olay / ramak kala | Rutin inceleme notları | Olayın ilgili sorumluya aktarımı bir kez; kritik olay ayrı politika | İSG/saha sorumlusu; olayın gerçek önem derecesine göre |
| İş izinleri | Rutin form alanları | Yetkiliye onay talebi bir kez; askıya alma/iptal kritik politika | Süresi biten izinde site durumu anında değişmeli; işe devam kararı haftalık maile bırakılamaz |
| Eğitim / yeterlilik | Katılım ve sertifika ekleme | Atama, T-7, T-1; süreli yeterlilikte T-30, T-7, T | Yalnızca tamamlamayan kişi ve ilgili eğitim sorumlusu; sonra haftalık |
| Toplantı notları | Her tutanak düzenlemesi | Katılımcıya kesinleşen davet bir kez, T-1; saat/yer değişikliği veya iptal bir kez | Karardan açılan aksiyon ortak aksiyon politikasını kullanır |
| YGG | Girdi ve tutanak düzenlemeleri | Katılımcıya kesinleşme, T-7, T-1; hazırlık görevi ilgili sahibine | Karar aksiyonları haftalık; toplantı ve aksiyon iki farklı sorumluluksa ayrı satır |
| Tedarikçi değerlendirme | Firma kartı, ara puanlama | Değerlendiriciye T-30, T-7, T | Eksik değerlendirme haftalık; dış tedarikçiye iç değerlendirme maili yok |
| Kalite hedefleri / KPI | Her veri girişi ve grafik değişimi | Ölçüm döneminin sonunda veri eksikse sahibine bir kez | Eksik veri haftalık; yönetime aylık dönem özeti, günlük grafik maili yok |
| Süreç yönetimi / ilgili taraflar | Süreç kartı ve beklenti güncellemesi | Gözden geçirme T-30, T-7, T | Süreç sahibine haftalık açık iş özeti |
| Yasal şartlar / mevzuat | Her tarama veya ham kaynak değişikliği | İlgili sorumluya doğrulanmış ve uygulanabilir değişiklik bir kez; T-30, T-7, T | Süresi geçmiş yükümlülükte yetkiliye bir kez; devamı riskine göre. Hukuki yeterlilik ayrı değerlendirilir |
| Değişiklik / sapma / uygunsuz ürün | Taslak ve normal açıklamalar | Onay isteği; T-7, T; karantina/serbest bırakma gibi işlem gerektiren karar bir kez | Süreç sahibi/karar yetkilisi; kritik kararda kritik politika |
| Saha kontrol / 5S / dinamik form | Başarılı rutin kontroller | Görev ataması; planlı kontrol günü eksikse bir kez | Bulgudan açılan aksiyon ortak politika; günlük zorunlu kontrol için şirketçe ayrıca onaylanan düzen |
| Kaizen / A3 / 8D | Rutin adım güncellemesi | Aşama onayı; T-7, T | Sorumluya haftalık; bağlantılı aksiyon maili tekrar edilmez |
| Alınan dersler | Yeni yayın ve rutin düzenlemeler | Varsayılan e-posta yok | İlgili kullanıcıya site bildirimi; zorunlu eğitim atanırsa eğitim politikası |
| Resmî yazışma / arşiv | Arşivleme, rutin dosya ekleri | Sorumluya havale/yanıt isteği; T-3, T | Yanıt bekleyen iş haftalık; hassas ekler mailde taşınmaz |
| Cihaz / ekipman yaşam döngüsü | Envanter düzenlemesi | Zimmet/kabul/onay isteyen işlem bir kez | Bakım ve kalibrasyon hatırlatmaları kendi modülünden, çift bildirim yok |
| İç talep / Help Desk | Rutin iç notlar | Atama/yanıt isteği bir kez; SLA yaklaşımı/ihlali bir kez | Günlük tekrar yok; normal açık iş haftalık. Saatlik SLA için ayrı kritik kural gerekli |
| Tehlikeli maddeler / çevre / atık | Rutin envanter ve teslim girişi | Belge/gözden geçirme T-30, T-7, T; önemli uygunsuzluk bir kez | İlgili sorumlu; ciddi olay kritik politika, normal eksikler haftalık |
| Enerji | Normal sayaç okumaları | Eksik dönem okuması bir kez; tanımlı ciddi sapma ilk oluşumda | Açık aksiyon haftalık; yönetime aylık sonuç özeti |
| İş akışı tasarımcısı | Şablon/diyagram değişiklikleri | Aktif adımın görev/onay sahibine bir kez; T-3, T | Sonuçlanmayan adım haftalık; gelecekteki adımlara önceden mail yok |
| Personel / organizasyon / departman | Ekleme, düzenleme, silme, görev/telefon değişimi | Varsayılan e-posta yok | Yalnızca yetkiliye site bildirimi; audit kaydı korunur |
| Yönetici özetleri / termin paneli | Her sayaç ve tablo değişikliği | İlgili yöneticinin pazartesi özeti; aylık KPI bölümü | Mevcut özetle birleştirilir; ayrıca aynı kayıt için ikinci mail yok |
| Rapor / içe aktarma | Başarılı indirme ve küçük senkron işler | Uzun süren rapor hazırsa kullanıcı tercihine göre bir kez; başarısız iş sorumluya bir kez | Tekrar eden aynı hata tek olay altında; açık dosya eki yerine güvenli bağlantı |
| Admin / yedek / entegrasyon | Başarılı yedek, başarılı webhook, rutin audit kayıtları | Son denemeden sonra başarısızlık, servis kesintisi, yedek alınamaması ilgili teknik yetkiliye | Operasyonel alarm ayrı politika; her başarısız deneme ayrı mail değil |
| Proje planlama / SWOT (gelecek kapsam) | Rutin plan ve analiz değişiklikleri | Proje görevleri aksiyon politikasını, SWOT gözden geçirmesi T-30/T-7/T politikasını kullanmalı | Henüz mevcut merkezi hatırlatmada çalışıyor varsayılmaz; geliştirilirken uyarlanır |

## 6. Kritik durumlar ve 08:30 kuralı

Mevcut talep uyarınca planlı hatırlatma saati 08:30 olarak korunmalı. Yeni bir kritik olayda site bildirimi anında oluşmalı; varsayılan e-posta sıradaki 08:30'a girmeli. Ancak olay, iş izni iptali, ciddi ürün güvenliği riski veya servis kesintisini yalnızca sabah mailine bağlamak yeterli değildir.

Onaya sunulan istisna: yalnızca kritik güvenlik/operasyon olaylarında saat dışı bir kez e-posta ve tanımlı acil iletişim süreci. Bu istisna kullanıcı onayı olmadan açılmamalı. E-posta bir acil müdahale sistemi değildir. Kritikliğin kim tarafından ve hangi eşikle belirleneceği şirket politikasında tanımlanmalı.

Kritik durum hâlâ çözülmediyse günlük tekrar yerine 24 saat sonra sorumlu yöneticiye, 72 saat sonra süreç sahibine birer yükseltme önerilir. Aynı aşamada sürekli mail yok. Daha kısa yanıt gerektiren süreçlerde bu aralıklar uygun olmayabilir; süreç sahibi ayrı süre belirlemeli.

Kullanıcının talep ettiği şifre sıfırlama, hesap daveti veya müşteri doğrulama bağlantısı termin hatırlatması değildir; işlem sırasında bir kez gönderilmesi önerilir. Bildirim azaltma ayarı bu akışları yanlışlıkla bozmamalı.

## 7. Kimler almalı?

- Personel: yalnızca kendi görevi, eğitim/okuma yükümlülüğü ve kendisinden istenen işlem.
- Departman yöneticisi: kendi departmanının haftalık özeti ve belirlenen gecikme yükseltmeleri.
- Yönetim temsilcisi: kendi onayları, kritik KYS olayları ve şirket kalite özeti. Her personelin her değişikliğinin kopyası değil.
- Yönetim: haftalık istisna özeti ve aylık hedef sonuçları; operasyonel detaylar yerine karar gerektiren başlıklar.
- Süper admin: platform sağlığı ve teknik alarmlar. Varsayılan olarak bütün şirketlerin iş kayıtlarının e-postasını almaz.
- Görüntüleyici: varsayılan site içi; ayrıca yasal/işlevsel olarak atanan bir görev yoksa rutin e-posta yok.
- Müşteri/tedarikçi: yalnızca kendisine açık dış iletişim. İç değerlendirme, bireysel puan, iç not veya personel verisi içermez.

## 8. E-posta örneği

Konu: [Şirket Adı] Haftalık işleriniz: 2 onay, 3 yaklaşan termin, 1 gecikme

- Onayınızı bekliyor: PR.12 revizyon talebi. Bekleme: 3 gün.
- Bu hafta: CK01 kalibrasyonu. Termin: 09.10.2026. Yapılacak: planlama ve sertifika kaydı.
- Geciken: ICD-2026-0041 bulgu yanıtı. Termin: 01.07.2026. Yapılacak: bulguları yanıtlayın.

Her satırda yalnızca kayıt kodu, kısa konu, gereken işlem, termin ve doğru şirket alan adına bağlı bağlantı bulunmalı. E-posta gereksiz ek, uzun açıklama veya hassas değerlendirme puanı taşımamalı. Gönderen görünen adı şirkete göre değişebilir; gönderen adresi yalnızca doğrulanmış e-posta alan adıyla yapılandırılmalı.

## 9. Uygulama taslağı

1. Şirkete özel Bildirim Politikaları ekranı: modül, olay, kanal, tarih eşikleri, haftalık gün, alıcı rolü, yükseltme ve istisna ayarları. Değişiklikler audit log'a yazılır.
2. Kullanıcı tercihleri: şirketin izin verdiği kapsamda site içi / haftalık özet / önemli olaylar. Zorunlu iş akışı site içinde görünmeye devam eder; tercih yetki vermez.
3. Mevcut site bildirimi üretimini e-posta kararından ayır. Aksiyon, DÖF, doküman, araç ve müşteri portalındaki doğrudan gönderim yollarını da kapsa.
4. Bildirim olayı ile kalıcı gönderim kuyruğunu aynı veritabanı işleminde kaydet; işlem geri alınırsa mail çıkmasın. Gönderici, yalnızca commit edilmiş ve gönderim zamanı gelmiş işleri alsın.
5. Tekrar anahtarı: şirket + kullanıcı + asıl iş + olay/aşama + termin/sahiplik sürümü. Haftalık özet için ayrıca şirketin yerel hafta anahtarı. Veritabanında benzersizlik ve çalışanlar arası kilitleme kullan.
6. Gönderim öncesi üyelik, aktif kullanıcı, güncel yetki, modül açıklığı, görev durumu ve tenant alan adını yeniden doğrula. Eski sorumluya kuyruktan mail gitmesin.
7. Başarılı/kuyrukta/başarısız/iptal durumlarını ayır. Kuyruğa kabulü teslim edilmiş sayma; SMTP kabulü ile posta kutusuna teslimi de aynı kavram olarak gösterme.
8. Geçici hataları sınırlı tekrar denemeyle ele al. SMTP sonucunun belirsiz olduğu bağlantı kopmalarında kör yeniden gönderim yerine belirsiz durum ve inceleme kaydı kullan; SMTP ile kusursuz tek teslim garantisi verilmez.
9. Zamanlayıcı kesintisinde kaçırılan bütün eski mailleri yığma. Sonraki 08:30'da güncel tek özet üret; acil eşiklerin gecikmesini teknik alarm olarak kaydet.
10. Geçişte eski bildirim ve audit geçmişi korunmalı. Önce bir şirkette yalnızca gönderim önizlemesi, sonra onaylı pilot. Geri dönüş, eski günlük yığılmayı otomatik yeniden açmamalı.

## 10. Uygulama ve kabul checklisti

- [x] Merkezi hatırlatma mantığı ve ayrı gönderim yolları kaynak koddan incelendi.
- [x] Resmî rakip kaynakları incelendi; bilinmeyen sıklıklar açıkça ayrıldı.
- [x] Modül, alıcı, kanal ve tekrar aralığı önerisi hazırlandı.
- [x] Ürün sahibi temel politikayı ve canlıya alma çalışmasını onayladı.
- [ ] Saat dışı kritik e-posta istisnası ayrıca onaylandı; onay olmadan kapalı kalır.
- [x] Şirket bazlı politika ve kullanıcı tercihleri geliştirildi.
- [x] Merkezî olay/kuyruk/birleştirme mantığı geliştirildi.
- [ ] Doküman, aksiyon, DÖF, araç ve diğer bağımsız yollar aynı politikaya bağlandı.
- [x] Aynı eski gecikme salı, çarşamba ve perşembe yeniden mail üretmiyor; pazartesi özette görünüyor.
- [x] Tarih eşikleri ve haftalık özet aynı güne gelince kayıt yalnızca bir kez görünüyor.
- [ ] Kapanan, iptal edilen, yeniden atanan veya yetkisi kaldırılan iş gönderimden çıkıyor.
- [ ] Onay bekleyen iş yanlış kişiyi değil mevcut onaycıyı uyarıyor.
- [ ] Bir öneriyi değerlendiren kullanıcıya değerlendirme hatırlatması gitmiyor; bekleyen kullanıcıya gidiyor.
- [ ] Aynı bağlı aksiyon toplantı/risk/DÖF üzerinden mükerrer e-posta üretmiyor.
- [ ] Şirket izolasyonu, doğru alan adı, devre dışı modül ve pasif kullanıcı testleri başarılı.
- [ ] Europe/Istanbul 08:30, hafta sınırı, tarih değişikliği ve servis kesintisi senaryoları başarılı.
- [ ] Eşzamanlı çalışanlar, rollback ve başarısız SMTP senaryoları test edildi.
- [ ] Mobilde özet okunuyor; bağlantı login sonrası doğru şirkette doğru kaydı açıyor.
- [ ] 7 günlük göndermesiz önizleme ve ardından 2 haftalık pilot ölçüldü.
- [ ] Kritik olay kapsaması kaybolmadan rutin mail hacmini en az %70 azaltma hedefi ölçüldü; bu hedef ölçüm öncesi garanti değildir.
- [ ] Doğrulanmış yedek, migration provası, bağımsız QA ve canlıya alma onayı tamamlandı.

Öncelik: önce günlük tekrarın ve gereksiz alıcıların azaltılması; ardından gelişmiş istisnalar. Araştırma tarihi ile uygulama/yayın kanıtları birbirinden ayrıdır. İşaretlenmeyen ölçüm ve gelişmiş kapsam maddeleri tamamlandı sayılmaz.

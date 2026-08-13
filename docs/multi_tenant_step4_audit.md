# Multi-Tenant Adım 4 İzolasyon Kontrolü

Bu kontrol şirket bazlı yapıya geçişte route, model ve numara üretimi risklerini
incelemek için hazırlanmıştır. Bu adımda çalışma mantığı değiştirilmemiştir.

## Güvenli Görünen Alanlar

- `Action`, `ActionSubTask`, `Dof`, `Document`, `MaintenanceFault`,
  `MaintenanceMachine`, `InternalAudit`, `OrientationNode` detay/düzenle/sil
  route'larında kayıt alındıktan sonra `ensure_same_company(...)` kontrolü
  büyük ölçüde uygulanmış durumda.
- Liste sorgularında ana kayıtlar çoğunlukla `scoped_query(...)` üzerinden
  şirket filtresiyle çekiliyor.
- Bildirim sayfaları `Notification` için `scoped_query(...)` kullanıyor.
- Dosya indirme route'larında ana kayıt önce şirket kontrolünden geçiyor:
  doküman, IF dosyaları, aksiyon dosyaları ve kapanış kanıtları.

## Dikkat Edilmesi Gereken Alanlar

- `DocumentCategory.slug` model ve migration seviyesinde global unique.
  Bu nedenle kategori kayıtlarını şirket bazlı çoğaltmak şu an doğrudan güvenli
  değil. Aynı `slug` yeni şirket için tekrar oluşturulursa veritabanı çakışır.
- `Action.action_number`, `Dof.dof_no`, `InternalAudit.audit_no`,
  `MaintenanceFault.fault_number` gibi alanlar modelde global unique veya fiilen
  global sayaç mantığıyla çalışıyor. Yeni firmalarda numaranın `1`den başlaması
  istenirse önce unique constraint yapısı company bazlı hale getirilmeli.
- `AppSetting` tablosunda `company_id` alanı var; fakat sayaç ayarları hâlâ bazı
  yerlerde global key mantığına dayanıyor. Şirket bazlı sayaç için migration ve
  geriye dönük key taşıma planı gerekir.

## Bu Adımda Kod Değişikliği Yapılmayan Yerler

- Route davranışları değiştirilmedi.
- Veritabanı migration eklenmedi.
- Unique constraint yapısı değiştirilmedi.
- Kategori ve sayaç mantığı canlı sistemi riske atmamak için değiştirilmedi.

## Önerilen Sonraki Adım

Şirket bazlı numara ve kategori ayrımı için ayrı bir migration hazırlanmalı:

1. Global unique alanlar tespit edilmeli.
2. Gerekirse unique indexler `(company_id, alan)` şeklinde yeniden kurulmalı.
3. `AppSetting` sayaç keyleri şirket bazlı hale getirilmeli.
4. Mevcut Er Prefabrik kayıtları `001` altında korunmalı.
5. Yeni şirketlerde kayıt numaralarının hangi formatla başlayacağı netleştirilmeli.

Bu adım tamamlanmadan sayaçları şirket bazlı yapmak canlıda kayıt oluşturma
hatalarına yol açabilir.

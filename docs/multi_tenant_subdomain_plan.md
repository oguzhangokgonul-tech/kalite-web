# VolkaPortal Subdomain Bazlı Multi-Tenant Planı

Bu plan şirket kodu alanını kullanıcıya göstermeyen, şirketi URL/subdomain
üzerinden otomatik seçen yapıya geçiş için hazırlanmıştır.

## Hedef Konsept

Kullanıcı şirket kodu yazmayacak.

Örnek adresler:

- `erprefabrik.volkaportal.com` -> Er Prefabrik
- `deneme.volkaportal.com` -> Deneme Hesabı
- `ornekfirma.volkaportal.com` -> Yeni firma

Sistem gelen `Host` bilgisinden firmayı bulacak ve tüm kayıtları o firmanın
`company_id` değeriyle çalıştıracak.

## Temel Karar

`company_id` veritabanında kalacak. Bu alan şirket ayrımı için gereklidir.

Kaldırılacak olan şey:

- Login ekranındaki kullanıcıya görünen `Şirket Kodu` alanı
- Kullanıcının manuel şirket kodu girmesi

Kalacak olan şey:

- `companies` tablosu
- `company_id` ilişkileri
- Superadmin şirket değiştirme yetkisi
- İç sistemde şirket kodu veya firma slug değeri

## Şirket Tablosu Genişletmesi

`companies` tablosuna şu alanların eklenmesi önerilir:

- `slug`
  - Örnek: `erprefabrik`
  - `erprefabrik.volkaportal.com` adresini firmaya bağlar.
- `primary_domain`
  - Örnek: `erprefabrik.volkaportal.com`
- `custom_domain`
  - İleride özel domain bağlamak için kullanılabilir.

`code` alanı tamamen silinmemeli; iç referans olarak kalabilir.

## Login Akışı

1. Kullanıcı `erprefabrik.volkaportal.com/login` adresine girer.
2. Sistem `Host` bilgisini okur.
3. `erprefabrik` slug değeriyle şirket bulunur.
4. Login ekranında şirket kodu alanı gösterilmez.
5. Kullanıcı adı ve şifre kontrol edilir.
6. Kullanıcı sadece o şirkete aitse giriş yapabilir.
7. Superadmin tüm şirketlere girebilir veya ana panelden şirket seçebilir.

## Superadmin Akışı

Superadmin için iki seçenek önerilir:

1. `admin.volkaportal.com`
   - Tüm şirketleri görebileceği merkezi panel.
2. Ana domain veya mevcut domain
   - Şirket seçici üzerinden firmalar arasında geçiş.

Superadmin bir tenant subdomain’indeyse o şirket bağlamında işlem yapabilir.

## Unique Çakışma Konusu

Subdomain kullanmak kullanıcı deneyimini iyileştirir ama veritabanındaki global
unique çakışmaları tek başına çözmez.

Şu alanlar hâlâ dikkat ister:

- `Action.action_number`
- `Dof.dof_no`
- `InternalAudit.audit_no`
- `MaintenanceFault.fault_number`
- `MaintenanceMachine.code`
- `DocumentCategory.slug`
- `User.username`

Eğer her firma kendi içinde `0001`den başlasın istenirse bu alanlar şirket bazlı
unique yapılmalıdır.

Örnek:

- Eski: `dof_no` global unique
- Yeni: `(company_id, dof_no)` unique

Alternatif olarak numaralar global kalabilir. Bu durumda çakışma olmaz ama yeni
firma `0001`den başlamaz.

## Önerilen Uygulama Sırası

### Adım 5 - Subdomain Alanlarını Ekle

- `companies.slug` alanı eklenir.
- Mevcut firmalar için slug atanır:
  - `001 Er Prefabrik` -> `erprefabrik`
  - `000 Deneme Hesabı` -> `deneme`
- Slug benzersiz yapılır.

### Adım 6 - Tenant Resolver Yaz

- `request.host` içinden subdomain okunur.
- Subdomain şirket slug değeriyle eşleştirilir.
- `g.current_company` bu bilgiyle set edilir.
- Local geliştirme için fallback korunur.

### Adım 7 - Login Ekranından Şirket Kodu Alanını Kaldır

- Login formundan `company_code` input’u kaldırılır.
- Login route’u şirketi formdan değil host/subdomain’den alır.
- Hatalı subdomain için uygun hata sayfası veya yönlendirme hazırlanır.

### Adım 8 - Superadmin Şirket Geçişini Subdomain Mantığına Uydur

- Superadmin şirket seçince ilgili subdomain’e yönlenir.
- Local ortamda session bazlı şirket seçimi fallback olarak kalabilir.

### Adım 9 - Unique ve Sayaç Migration Planı

Bu adım ayrı ve dikkatli yapılmalıdır.

Karar verilmesi gereken konu:

- Her firma kendi içinde `0001`den mi başlayacak?
- Yoksa global sıra devam mı edecek?

Firma bazlı sıra istenirse:

- Global unique constraintler kaldırılır.
- Composite unique constraintler eklenir.
- Sayaç `AppSetting` keyleri şirket bazlı yapılır.

### Adım 10 - DNS ve Sunucu Ayarı

`erprefabrik.volkaportal.com` için:

- DNS tarafında wildcard veya tekil subdomain kaydı açılır.
- Nginx `server_name` yapısı subdomainleri karşılayacak hale getirilir.
- SSL sertifikası wildcard veya çoklu domain destekli düzenlenir.

## Canlıya Geçiş Notu

Kod düzenlemeleri tamamlandıktan sonra ilk canlı senaryo:

1. `erprefabrik.volkaportal.com` DNS kaydı oluşturulur.
2. Nginx bu subdomain’i Flask uygulamasına yönlendirir.
3. `companies.slug = erprefabrik` kontrol edilir.
4. Oğuzhan kullanıcısı Er Prefabrik şirketinde test login yapar.
5. Aksiyon, IF, doküman, iç denetim ve bildirim izolasyonu test edilir.

## Kısa Sonuç

Şirket kodu kullanıcıdan kaldırılabilir. En doğru SaaS yaklaşımı subdomain bazlı
tenant seçimidir. Ancak veritabanındaki numara ve kategori unique yapısı ayrı bir
migration gerektirir; bu kısım aceleyle değiştirilmemelidir.

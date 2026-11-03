# VolkaPortal Windows uygulaması

Bu sürüm, mevcut VolkaPortal sunucusuna HTTPS üzerinden bağlanan Windows masaüstü istemcisidir. Sunucu kodu, veritabanı, yüklenen dosyalar ve gizli ayarlar kurulum paketine dahil edilmez. İnternet bağlantısı gerekir. Kullanıcı ve Superadmin yetkileri sunucudaki mevcut kurallarla belirlenir.

Şu an `volkaportal.com` ve tek seviyeli `*.volkaportal.com` adresleri uygulama içinde açılır. Özel firma domainleri varsayılan tarayıcıda açılır; o tarayıcıda ayrı oturum gerekebilir. Sunucu tarafındaki değişiklikler istemciyi yeniden kurmadan görünür, ancak masaüstü kabuğundaki değişiklikler için yeni kurucu gerekir.

## Derleme

Windows x64 üzerinde .NET 10 SDK ve Inno Setup 6 kurulu olmalıdır:

```powershell
./desktop/build-installer.ps1
```

Çıktı sürüm numarasıyla `desktop/dist/VolkaPortal-Setup-0.1.6-win-x64.exe` konumundadır. Pencere, kurucu ve kısayollar geyik simgesini kullanır. Uygulama varsayılan olarak %67 yakınlaştırmayla ve ek araç çubuğu olmadan açılır. Yenileme için `F5` veya `Ctrl+R`, geri/ileri için `Alt+Sol` / `Alt+Sağ` kullanılabilir. Kurucu WebView2 Runtime'ı Microsoft imzalı bootstrapper ile sağlar. Kurulum dosyası henüz kod imzalı değildir; müşterilere yaygın dağıtım öncesinde yayıncı sertifikasıyla imzalanmalıdır.

Kurucu yeniden açıldığında kurulu sürüm için **Güncelle / Yeniden kur** ve **Kaldır** seçenekleri gösterilir. Başlat menüsündeki **VolkaPortal Kaldır** kısayolu veya Windows'un Yüklü uygulamalar ekranı da kullanılabilir. Kaldırırken yerel oturum ve önbellek verilerini silme ayrıca sorulur; sessiz kaldırma bunları varsayılan olarak korur. Sunucudaki kayıtlar, indirilen dosyalar ve başka uygulamaların kullandığı WebView2 Runtime kaldırılmaz.

## Güncelleme

0.1.5 ve sonraki masaüstü sürümleri açılışta ve saat başı `https://volkaportal.com/desktop-updates/latest.json` adresini kontrol eder. Daha yeni sürüm varsa üstte küçük bir **Güncelleme gerekli** bandı ve **Sistemi güncelle** düğmesi görünür. Kullanıcı onayından sonra kurucu indirilir, bildirimin ECDSA imzası ve kurucunun boyut/SHA-256 özeti doğrulanır, sessiz kurulum yapılır ve uygulama yeniden açılır. Bağlantı yoksa mevcut sürüm çalışmaya devam eder. 0.1.4 ve daha eski kurulumlarda bu denetim yoktur; 0.1.5 bir kez elle kurulmalıdır. Sunucu tarafındaki sayfa değişiklikleri için yeni masaüstü kurucusu gerekmez.

Kurucu ve imzalı bildirim birlikte hazırlanır:

```powershell
./desktop/build-installer.ps1
./desktop/prepare-update-release.ps1
dotnet run --project desktop/VolkaPortal.Desktop.Tests -c Release -- desktop/dist/release/latest.json
```

Yayınlanacak iki dosya `desktop/dist/release/` altındadır: `latest.json` ve bildirimin adlandırdığı `.exe`. Sunucuda bunlar `DESKTOP_UPDATE_DIR` klasörüne (varsayılan `DATA_DIR/desktop-updates`) `aksiyon` kullanıcısının okuyabileceği şekilde konulmalıdır. Önce EXE'yi, son olarak `latest.json` dosyasını yayınlayın; böylece istemci yarım yüklenmiş sürümü görmez. `latest.json` imzalı olduğundan dosyaları elle değiştirmeyin. İmza özel anahtarı yalnızca yayın bilgisayarında, depo dışında tutulmalı ve güvenli yedeklenmelidir. Yeni sürümün daha düşük numaralı kurucuya dönmesi engellenir. Kod imzası ayrı bir güvenlik katmanıdır; şu an bulunmadığı için Windows SmartScreen uyarısı görülebilir.

Derleme URL politikası ve sürüm bildirimi testlerini çalıştırır. 0.1.4 kurucusunun Türkçe bakım menüsü ve kaldırma onayı kurulu 0.1.3 üzerinde doğrulandı; mevcut oturumu korumak için gerçek kaldırma bu bilgisayarda çalıştırılmadı. 0.1.5'in sessiz güncelleme/yeniden açılma akışı kurulu istemci üzerinde henüz uçtan uca doğrulanmadı. Kimlik doğrulama, rapor indirme, dosya yükleme, yazdırma ve bütün modül iş akışları gerçek kullanıcı oturumlarıyla ayrıca kabul testinden geçirilmelidir.

## Güvenlik sınırı

İstemci kaynak kodunu pakete koymamak, sunucu uygulamasını korur; ancak tarayıcıya gönderilen HTML/CSS/JavaScript gizlenemez. GitHub deposunun özel olması ve sunucu erişiminin ayrı korunması gerekir. İstemciye Superadmin şifresi, API anahtarı veya kalıcı oturum gömülmez.

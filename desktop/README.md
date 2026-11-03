# VolkaPortal Windows uygulaması

Bu sürüm, mevcut VolkaPortal sunucusuna HTTPS üzerinden bağlanan Windows masaüstü istemcisidir. Sunucu kodu, veritabanı, yüklenen dosyalar ve gizli ayarlar kurulum paketine dahil edilmez. İnternet bağlantısı gerekir. Kullanıcı ve Superadmin yetkileri sunucudaki mevcut kurallarla belirlenir.

Şu an `volkaportal.com` ve tek seviyeli `*.volkaportal.com` adresleri uygulama içinde açılır. Özel firma domainleri varsayılan tarayıcıda açılır; o tarayıcıda ayrı oturum gerekebilir. Sunucu tarafındaki değişiklikler istemciyi yeniden kurmadan görünür, ancak masaüstü kabuğundaki değişiklikler için yeni kurucu gerekir.

## Derleme

Windows x64 üzerinde .NET 10 SDK ve Inno Setup 6 kurulu olmalıdır:

```powershell
./desktop/build-installer.ps1
```

Çıktı sürüm numarasıyla `desktop/dist/VolkaPortal-Setup-0.1.6-win-x64.exe` konumundadır. Pencere, kurucu ve kısayollar geyik simgesini kullanır. Uygulama varsayılan olarak %67 yakınlaştırmayla ve ek araç çubuğu olmadan açılır. Yenileme için `F5` veya `Ctrl+R`, geri/ileri için `Alt+Sol` / `Alt+Sağ` kullanılabilir. Kurucu WebView2 Runtime'ı Microsoft imzalı bootstrapper ile sağlar. Parametresiz derleme yalnızca imzasız yerel geliştirme içindir; dağıtıma uygun değildir.

## Windows kod imzası

Güvenilir bir OV kod imzalama sertifikası henüz yoktur. Sertifika edinildikten ve Windows sertifika deposunda (`Cert:\CurrentUser\My`) özel anahtarıyla erişilebilir olduktan sonra Windows SDK `signtool.exe` ile imzalı derleme yapılır. Bireysel OV başvurusunda yayıncı adı CA tarafından doğrulanan gerçek kişi adı (örneğin Oğuzhan Gökgönül) olabilir. Şirket tüzel kişiliği teyitli değildir; VolkaPortal markasının ayrıca tescili/doğrulaması olmadan sertifika yayıncı adında görünmesi garanti değildir. Sertifikanın gerçek `Subject` değerini ve kod imzalama kullanımını CA onayından sonra kontrol edin; scriptte ad sabit değildir.

```powershell
$thumbprint = '<sertifikanin-40-haneli-thumbprint-degeri>'
$publisherSubject = '<CA-tarafindan-onaylanan-tam-sertifika-Subject-degeri>'
$timestampUrl = 'https://<CA-RFC3161-timestamp-adresi>'
./desktop/build-installer.ps1 -CertificateThumbprint $thumbprint -ExpectedPublisherSubject $publisherSubject -TimestampUrl $timestampUrl
./desktop/prepare-update-release.ps1 -CertificateThumbprint $thumbprint -ExpectedPublisherSubject $publisherSubject
dotnet run --project desktop/VolkaPortal.Desktop.Tests -c Release -- desktop/dist/release/latest.json
```

`signtool.exe` PATH veya Windows SDK x64 konumunda bulunamazsa her iki scripte `-SignToolPath` verin. Build, yayımlanan `VolkaPortal.Desktop.exe` dosyasını SHA-256/RFC3161 ile imzalayıp `verify /pa` ile doğrular. Inno `SignTool`, kurucuyu, kaldırıcıyı ve geçici kopyalarını imzalar. Release hazırlığı kurucuyu ve yayın klasöründeki kopyasını `verify /pa`, sertifika thumbprint'i, tam yayıncı `Subject` değeri ve zaman damgasıyla yeniden doğrular. WebView2 bootstrapper'ın mevcut Microsoft imza kontrolü korunur. Token PIN'i veya özel anahtarı komut satırına, ortam değişkenine, loga ya da depoya koymayın; donanım tokenı gerekiyorsa PIN'i yalnızca sağlayıcının güvenli isteminde girin.

Üretim release'i sertifika parametreleri veya geçerli imza olmadan başarısız olur. `-LocalTestOverride` yalnızca `prepare-update-release.ps1` için açıkça seçilen imzasız yerel manifest denemesidir; çıktılar ayrı `desktop/dist/local-test-release/` klasörüne yazılır ve yayımlanmamalıdır.

Kurucu yeniden açıldığında kurulu sürüm için **Güncelle / Yeniden kur** ve **Kaldır** seçenekleri gösterilir. Başlat menüsündeki **VolkaPortal Kaldır** kısayolu veya Windows'un Yüklü uygulamalar ekranı da kullanılabilir. Kaldırırken yerel oturum ve önbellek verilerini silme ayrıca sorulur; sessiz kaldırma bunları varsayılan olarak korur. Sunucudaki kayıtlar, indirilen dosyalar ve başka uygulamaların kullandığı WebView2 Runtime kaldırılmaz.

## Güncelleme

0.1.5 ve sonraki masaüstü sürümleri açılışta ve saat başı `https://volkaportal.com/desktop-updates/latest.json` adresini kontrol eder. Daha yeni sürüm varsa üstte küçük bir **Güncelleme gerekli** bandı ve **Sistemi güncelle** düğmesi görünür. Kullanıcı onayından sonra kurucu indirilir, bildirimin ECDSA imzası ve kurucunun boyut/SHA-256 özeti doğrulanır, sessiz kurulum yapılır ve uygulama yeniden açılır. Bağlantı yoksa mevcut sürüm çalışmaya devam eder. 0.1.4 ve daha eski kurulumlarda bu denetim yoktur; 0.1.5 bir kez elle kurulmalıdır. Sunucu tarafındaki sayfa değişiklikleri için yeni masaüstü kurucusu gerekmez.

Kurucu ve imzalı bildirim yukarıdaki imzalı derleme ve release adımlarıyla birlikte hazırlanır. Yalnızca yerel geliştirme denemesi için:

```powershell
./desktop/build-installer.ps1
./desktop/prepare-update-release.ps1 -LocalTestOverride
dotnet run --project desktop/VolkaPortal.Desktop.Tests -c Release -- desktop/dist/local-test-release/latest.json
```

İmzalı üretim hazırlığında yayınlanacak iki dosya `desktop/dist/release/` altındadır: `latest.json` ve bildirimin adlandırdığı `.exe`. Mevcut manifest varsa yeni sürüm kesinlikle daha büyük olmalı; aynı sürüm, hash değişmiş olsa da yeniden yayımlanamaz. Önce yeni sürümün kurucusu farklı dosya adıyla kopyalanıp hash/imza doğrulanır, ardından geçici dosyada hazırlanmış manifest atomik olarak `latest.json` yerine geçirilir. Hata halinde önceki manifest ve ona ait kurucu korunur. Sunucuda bunlar `DESKTOP_UPDATE_DIR` klasörüne (varsayılan `DATA_DIR/desktop-updates`) `aksiyon` kullanıcısının okuyabileceği şekilde konulmalıdır. Önce EXE'yi, son olarak `latest.json` dosyasını yayınlayın; böylece istemci yarım yüklenmiş sürümü görmez. `latest.json` imzalı olduğundan dosyaları elle değiştirmeyin. Manifest imza özel anahtarı yalnızca yayın bilgisayarında, depo dışında tutulmalı ve güvenli yedeklenmelidir. Kod imzası ayrı bir güvenlik katmanıdır; sertifika edinilene kadar Windows SmartScreen uyarısı görülebilir.

Derleme URL politikası ve sürüm bildirimi testlerini çalıştırır. 0.1.4 kurucusunun Türkçe bakım menüsü ve kaldırma onayı kurulu 0.1.3 üzerinde doğrulandı; mevcut oturumu korumak için gerçek kaldırma bu bilgisayarda çalıştırılmadı. 0.1.5'in sessiz güncelleme/yeniden açılma akışı kurulu istemci üzerinde henüz uçtan uca doğrulanmadı. Kimlik doğrulama, rapor indirme, dosya yükleme, yazdırma ve bütün modül iş akışları gerçek kullanıcı oturumlarıyla ayrıca kabul testinden geçirilmelidir.

## Güvenlik sınırı

İstemci kaynak kodunu pakete koymamak, sunucu uygulamasını korur; ancak tarayıcıya gönderilen HTML/CSS/JavaScript gizlenemez. GitHub deposunun özel olması ve sunucu erişiminin ayrı korunması gerekir. İstemciye Superadmin şifresi, API anahtarı veya kalıcı oturum gömülmez.

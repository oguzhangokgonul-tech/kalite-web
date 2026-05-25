# Aksiyon Takip Sistemi

Flask, SQLite, SQLAlchemy ve Bootstrap ile hazırlanmış kalite yönetim sistemi aksiyon takip uygulaması.

## Özellikler

- Aksiyon başlığı, aksiyon sorumlusu, açıklama, termin ve gecikme günü takibi
- Departman bazlı aksiyon takibi
- Ana sayfada arama, departman, sorumlu ve durum filtreleri
- Aksiyon geçmişi, site içi/e-posta bildirimleri ve ilgili kullanıcı takibi
- Termin tarihi geçen açık aksiyonları otomatik gecikmiş olarak gösterme
- Gecikme gününü otomatik hesaplama
- Tamamlanan aksiyonları yeşil, geciken aksiyonları kırmızı gösterme
- Yeni aksiyon ekleme, aksiyon düzenleme, silme ve hızlı tamamlama
- Yeni aksiyon eklerken PDF, Word, Excel ve görsel dosyası yükleme
- Yüklenen dosyaları ana sayfa üzerinden indirme
- Ana sayfa üzerinde toplam, tamamlanan ve geciken aksiyon sayıları
- Kullanıcı girişi, kullanıcı yönetimi ve yetki bazlı işlem kontrolleri
- Kendine atanmış aksiyona yorum yapma ve kapatma yetkisi
- Kendine atanmış aksiyonu başka kullanıcıya devredebilme
- Responsive Bootstrap arayüz
- Flask-Migrate migration yapısı

## Kurulum

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Bu projede sanal ortam klasörünüz `venv` ise komutlar:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Veritabanını Hazırlama

```bash
flask --app run.py db upgrade
```

Windows'ta `flask` komutu bulunamazsa:

```powershell
.\venv\Scripts\python.exe -m flask --app run.py db upgrade
```

Bu komut SQLite veritabanını oluşturur ve migration dosyalarını uygular.

Yüklenen dosyalar varsayılan olarak `instance/uploads` klasöründe saklanır.

İlk migration sonrasında varsayılan kullanıcılar otomatik oluşturulur:

```text
Kullanıcı adı: oguzhan
Şifre: kysoguzhan
Yetki: Tüm yetkiler

Kullanıcı adı: ufuk
Şifre: kysufuk
Yetki: Kendine atanmış aksiyonlara yorum yapma ve kapatma

Kullanıcı adı: seyma
Şifre: kysseyma
Yetki: Kendine atanmış aksiyonlara yorum yapma ve kapatma

Kullanıcı adı: turgut
Şifre: kysturgut
Yetki: Kendine atanmış aksiyonlara yorum yapma ve kapatma
```

## Çalıştırma

```bash
flask --app run.py run --debug --host 0.0.0.0 --port 5000
```

Windows'ta `flask` komutu bulunamazsa veya sanal ortamı aktive etmek istemiyorsanız:

```powershell
.\venv\Scripts\python.exe -m flask --app run.py run --host 0.0.0.0 --port 5000
```

Uygulama varsayılan olarak `http://127.0.0.1:5000` adresinde çalışır.
Yerel ağdaki başka bir cihazdan erişmek için bilgisayarınızın IP adresini kullanabilirsiniz:
`http://BILGISAYAR_IP_ADRESI:5000`

Port 5000 doluysa 5001 gibi boş bir port kullanabilirsiniz:

```powershell
.\venv\Scripts\python.exe -m flask --app run.py run --host 0.0.0.0 --port 5001
```

## E-posta Bildirimleri

Aksiyon açıldığında, kapatıldığında, yorum eklendiğinde veya aksiyon güncellendiğinde ilgili kullanıcılara e-posta gönderilebilir. Sistem SMTP ile çalışır; bu yüzden Google Workspace, Microsoft 365, şirket SMTP sunucusu veya SendGrid/Brevo/Amazon SES gibi herhangi bir SMTP servisi kullanılabilir. E-postalar arka planda gönderilir; SMTP yavaşlasa veya hata verse bile aksiyon kaydetme ekranı beklemez.

Yerel testte mail göndermeden entegrasyonu açmak için:

```powershell
$env:MAIL_ENABLED="true"
$env:MAIL_SUPPRESS_SEND="true"
```

Gerçek gönderim için örnek ayarlar:

```powershell
$env:MAIL_ENABLED="true"
$env:MAIL_SERVER="smtp.office365.com"
$env:MAIL_PORT="587"
$env:MAIL_USE_TLS="true"
$env:MAIL_USERNAME="aksiyon@ornek.com"
$env:MAIL_PASSWORD="mail-sifresi-veya-uygulama-sifresi"
$env:MAIL_DEFAULT_SENDER="aksiyon@ornek.com"
$env:PUBLIC_BASE_URL="https://site-adresiniz.com"
```

Google Workspace SMTP relay kullanıyorsanız `MAIL_SERVER` değeri genellikle `smtp-relay.gmail.com` olur. Microsoft 365 SMTP AUTH kullanıyorsanız `smtp.office365.com` ve port `587` kullanılır. Seçilen hizmette uygulama gönderimi/SMTP relay yetkisinin açık olması gerekir.

VPS üzerinde bu değerleri `/var/www/aksiyon-takip/.env` dosyasına ekleyebilirsiniz. `PUBLIC_BASE_URL`, maildeki aksiyon detay linkinin doğru site adresine gitmesi için önemlidir.

Sunucuda ayarları test etmek için:

```bash
cd /var/www/aksiyon-takip
sudo -u aksiyon ./venv/bin/python -m flask --app run.py test-mail kendi-adresiniz@ornek.com
```

### Gmail ile Gönderim

Outlook/Microsoft 365 ile uğraşmak istemiyorsanız ayrı bir Gmail hesabı üzerinden de bildirim gönderebilirsiniz. Normal Gmail şifresi yerine Google hesabında 2 adımlı doğrulamayı açıp uygulama parolası üretmeniz gerekir.

Proje klasöründe `.env.example` dosyasını kopyalayıp `.env` adıyla kaydedin ve kendi Gmail bilgilerinizi bu dosyada güncelleyin. `.env` dosyası git'e eklenmez; şifreler burada tutulur.

Örnek ayarlar:

```text
MAIL_ENABLED=true
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USE_SSL=false
MAIL_USERNAME=<gmail-adresiniz>@gmail.com
MAIL_PASSWORD=<16 haneli Google uygulama parolası>
MAIL_DEFAULT_SENDER=<gmail-adresiniz>@gmail.com
MAIL_REPLY_TO=Kalite@erprefabrik.com.tr
PUBLIC_BASE_URL=<yayındaki site adresi>
```

Gmail genellikle `From` alanında kendi Gmail adresinizi kullanmanızı bekler. Bu yüzden bildirimler Gmail adresinden gider; `MAIL_REPLY_TO` sayesinde kullanıcı cevap yazarsa yanıtlar şirket adresine yönlenebilir.

### Outlook / Microsoft 365 Ayarları

Şirket e-postası Outlook/Microsoft 365 ise en pratik başlangıç ayarı:

```text
MAIL_ENABLED=true
MAIL_SERVER=smtp.office365.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USE_SSL=false
MAIL_USERNAME=Kalite@erprefabrik.com.tr
MAIL_PASSWORD=<IT ekibinin vereceği uygulama parolası veya servis hesabı parolası>
MAIL_DEFAULT_SENDER=Kalite@erprefabrik.com.tr
PUBLIC_BASE_URL=<yayındaki site adresi>
```

IT ekibinden istenecekler:

- `Kalite@erprefabrik.com.tr` posta kutusunun aktif ve gönderim yapabilir olduğunu doğrulamaları.
- Bu posta kutusu için `Authenticated SMTP` ayarını açmaları.
- Tenant genelinde SMTP AUTH kapalıysa sadece bu posta kutusu için izin vermeleri.
- MFA/conditional access kullanılıyorsa uygulama gönderimine uygun parola veya izin tanımlamaları.
- Uzun vadede SMTP kullanıcı/parola yerine Microsoft Graph `Mail.Send` entegrasyonu isteniyorsa Azure App Registration bilgilerini sağlamaları.

## Render Üzerinde Başlatma

Render start command için şu komutu kullanın:

```bash
gunicorn run:app
```

Uygulama açılırken tabloları oluşturur ve varsayılan kullanıcıları eksikse otomatik ekler. Mevcut kullanıcıların görev, e-posta ve ad soyad bilgileri restart sırasında ezilmez. Oğuzhan kullanıcısının admin yetkileri korunur.

Varsayılan kullanıcı şifrelerini acil durumda tekrar üretmek için Environment bölümünde geçici olarak şu değeri kullanabilirsiniz:

```text
RESET_DEFAULT_USER_PASSWORDS=true
```

Normal kullanımda bu değeri kapalı bırakın veya hiç tanımlamayın.

Render Shell üzerinden kullanıcıları elle yenilemek gerekirse:

```bash
flask --app run.py seed-users
```

### Render'da Kayıtların Silinmemesi

Render free servislerde dosya sistemi geçicidir. Bu yüzden SQLite veritabanı ve yüklenen dosyalar servis yeniden başlatıldığında, yeniden deploy edildiğinde veya uyku modundan uyandığında silinebilir.

Kayıtların kalıcı olması için Render'da paid instance üzerine Persistent Disk ekleyin ve disk mount path değerini şu yapın:

```text
/var/data
```

Sonra Render Environment bölümüne şu değeri ekleyin:

```text
DATA_DIR=/var/data
```

Bu ayarla uygulama veritabanını `/var/data/actions.db`, yüklenen dosyaları `/var/data/uploads` altında saklar.

## Geçici Online Paylaşım

Kısa süreli dış erişim için:

```powershell
.\start-share.ps1
```

Komut size paylaşılabilir bir `https://...lhr.life` linki verir. Bilgisayar açık ve internet bağlantısı aktif kaldığı sürece 1-2 kişi bu linkten giriş yapabilir.

Paylaşımı kapatmak için:

```powershell
.\stop-share.ps1
```

## Dosya Yapısı

```text
.
+-- app/
|   +-- __init__.py
|   +-- config.py
|   +-- extensions.py
|   +-- models.py
|   +-- routes.py
|   +-- seed.py
|   +-- static/
|   |   +-- css/
|   |       +-- styles.css
|   +-- templates/
|       +-- action_form.html
|       +-- base.html
|       +-- confirm_delete.html
|       +-- dashboard.html
+-- migrations/
|   +-- alembic.ini
|   +-- env.py
|   +-- script.py.mako
|   +-- versions/
+-- requirements.txt
+-- README.md
+-- run.py
```

## Notlar

- Termin tarihi bugünden önceyse ve aksiyon tamamlanmamışsa gecikme günü otomatik hesaplanır.
- `Tamamla` butonu aksiyonu tamamlandı olarak işaretler ve gecikme gününü sıfırlar.
- Formda durum seçimi yoktur; açık, gecikmiş ve tamamlanmış görünüm sistem tarafından yönetilir.
- Departman seçenekleri: Üretim, Kalite, İnsan Kaynakları, Şantiye, Montaj, Proje, Teklif.
- Dosya yükleme için izin verilen uzantılar: `.pdf`, `.doc`, `.docx`, `.xls`, `.xlsx`, `.jpg`, `.jpeg`, `.png`, `.webp`.
- Oğuzhan kullanıcısı yönetici yetkilerine sahiptir.
- Yeni kullanıcılar ve yetkiler `Kullanıcılar` ekranından yönetilebilir.

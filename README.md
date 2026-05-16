# Aksiyon Takip Sistemi

Flask, SQLite, SQLAlchemy ve Bootstrap ile hazırlanmış kalite yönetim sistemi aksiyon takip uygulaması.

## Özellikler

- Aksiyon başlığı, aksiyon sorumlusu, açıklama, termin ve gecikme günü takibi
- Departman bazlı aksiyon takibi
- Ana sayfada arama, departman, sorumlu ve durum filtreleri
- Termin tarihi geçen açık aksiyonları otomatik gecikmiş olarak gösterme
- Gecikme gününü otomatik hesaplama
- Tamamlanan aksiyonları yeşil, geciken aksiyonları kırmızı gösterme
- Yeni aksiyon ekleme, aksiyon düzenleme, silme ve hızlı tamamlama
- Yeni aksiyon eklerken PDF, Word ve Excel dosyası yükleme
- Yüklenen dosyaları dashboard üzerinden indirme
- Dashboard üzerinde toplam, tamamlanan ve geciken aksiyon sayıları
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

İlk migration sonrasında iki kullanıcı otomatik oluşturulur:

```text
Kullanıcı adı: oguzhan
Şifre: kysoguzhan
Yetki: Tüm yetkiler

Kullanıcı adı: ufuk
Şifre: kysufuk
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

## Render Üzerinde Başlatma

Render start command için şu komutu kullanın:

```bash
gunicorn run:app
```

Uygulama açılırken tabloları oluşturur ve varsayılan kullanıcıları eksikse otomatik ekler. Varsayılan kullanıcı şifrelerini tekrar beklenen hale getirmek için Render Environment bölümünde şu değer açık kalabilir:

```text
RESET_DEFAULT_USER_PASSWORDS=true
```

Render Shell üzerinden kullanıcıları elle yenilemek gerekirse:

```bash
flask --app run.py seed-users
```

## Mail Ayarları

Aksiyon mailleri için önerilen yöntem Resend HTTP API'dir. Render Environment bölümüne şu değerleri ekleyin:

```text
MAIL_ENABLED=true
RESEND_API_KEY=re_xxxxxxxxx
RESEND_FROM=Aksiyon Takip <onboarding@resend.dev>
```

Resend'de kendi domaininiz doğrulandıysa `RESEND_FROM` değerini domaininizle kullanın:

```text
RESEND_FROM=Aksiyon Takip <aksiyon@erprefabrik.com.tr>
```

Not: Resend'in `onboarding@resend.dev` test adresi yalnızca Resend hesabınıza ait e-posta adresine gönderim için kullanılabilir. Diğer kullanıcılara göndermek için Resend'de domain doğrulamanız gerekir.

Mail ayarlarını Render Shell üzerinden test etmek için:

```bash
flask --app run.py test-mail oguzhangokgonul@gmail.com
```

SMTP kullanmak isterseniz aşağıdaki ayarlar da desteklenir.

Aksiyon açılınca ve kapanınca mail gönderimi için Render Environment bölümüne SMTP bilgileri eklenmelidir:

```text
MAIL_ENABLED=true
MAIL_SERVER=smtp_adresiniz
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USE_SSL=false
MAIL_USERNAME=mail_kullanici_adiniz
MAIL_PASSWORD=mail_sifreniz_veya_app_password
MAIL_DEFAULT_SENDER=mail_kullanici_adiniz
```

SMTP bilgileri girilmezse aksiyon işlemleri çalışmaya devam eder, sadece mail gönderilmez.

Render free servislerde klasik SMTP portları bloke olabilir. Gmail `smtp.gmail.com:587` ile `[Errno 101] Network is unreachable` alırsanız ayarlarınız doğru olsa bile Render SMTP çıkışını engelliyor olabilir. Bu durumda seçenekler:

- Render servisini paid instance'a almak
- SMTP2GO gibi `2525` portunu destekleyen bir servis kullanmak
- HTTP API ile çalışan Resend, SendGrid, Mailgun gibi bir servis kullanmak

Varsayılan e-posta tanımları:

```text
oguzhan -> oguzhangokgonul@erprefabrik.com.tr
seyma -> seymainci@erprefabrik.com.tr
turgut -> turgutpekyilmaz@erprefabrik.com.tr
ufuk -> e-posta tanımlı değil
```

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
- Dosya yükleme için izin verilen uzantılar: `.pdf`, `.doc`, `.docx`, `.xls`, `.xlsx`.
- Yeni kullanıcılar ve yetkiler `Kullanıcılar` ekranından yönetilebilir.

from sqlalchemy import inspect, text

from .extensions import db
from .models import AppSetting, Company, MaintenanceMachine, Role, User
from .maintenance_seed import MAINTENANCE_MACHINE_DEFAULTS


PERMISSION_CATALOG = (
    {
        "key": "iso_dashboard.view",
        "label": "ISO 9001 yönetici özetini görüntüleme",
        "group": "Yönetici Panelleri",
        "description": "ISO 9001 kalite göstergelerini ve kritik kayıt özetlerini görüntüler.",
    },
    {
        "key": "management_due_dashboard.view",
        "label": "Yönetici termin panelini görüntüleme",
        "group": "Yönetici Panelleri",
        "description": "Geciken ve 30 gün içinde yaklaşan yönetici terminlerini görüntüler.",
    },
    {
        "key": "roles.manage",
        "label": "Rol ve yetki yönetimi",
        "group": "Sistem",
        "description": "Rol hiyerarşisini, rol izinlerini ve kullanıcı rol atamalarını yönetir.",
    },
    {
        "key": "users.manage",
        "label": "Kullanıcı yönetimi",
        "group": "Sistem",
        "description": "Kullanıcı hesaplarını oluşturur ve düzenler.",
        "legacy_field": "can_manage_users",
    },
    {
        "key": "users.delete",
        "label": "Kullanıcı silme",
        "group": "Sistem",
        "description": "Kullanıcılar sayfasından personel kayıtlarını sistemden kaldırır.",
    },
    {
        "key": "actions.create",
        "label": "Aksiyon açma",
        "group": "Aksiyon",
        "description": "Yeni aksiyon kaydı oluşturur.",
        "legacy_field": "can_create_actions",
    },
    {
        "key": "actions.edit",
        "label": "Aksiyon düzenleme",
        "group": "Aksiyon",
        "description": "Yetkili olduğu aksiyon kayıtlarını düzenler.",
        "legacy_field": "can_edit_actions",
    },
    {
        "key": "actions.delete",
        "label": "Aksiyon silme",
        "group": "Aksiyon",
        "description": "Aksiyon kayıtlarını silebilir.",
        "legacy_field": "can_delete_actions",
    },
    {
        "key": "actions.comment_assigned",
        "label": "Atanan aksiyona yorum",
        "group": "Aksiyon",
        "description": "Kendisine atanan veya ilgili olduğu aksiyonlara yorum yapar.",
        "legacy_field": "can_comment_assigned_actions",
    },
    {
        "key": "actions.request_close_assigned",
        "label": "Atanan aksiyonu kapanışa gönderme",
        "group": "Aksiyon",
        "description": "Kendisine atanan aksiyon için kapanış onayı ister.",
        "legacy_field": "can_close_assigned_actions",
    },
    {
        "key": "actions.approve_closure",
        "label": "Aksiyon kapanış onayı",
        "group": "Aksiyon",
        "description": "Kapanış talebi gönderilen aksiyonu onaylar veya reddeder.",
    },
    {
        "key": "actions.view_all",
        "label": "Tüm aksiyonları görme",
        "group": "Aksiyon",
        "description": "Atama kısıtı olmadan tüm aksiyonları görebilir.",
    },
    {
        "key": "if.view_all",
        "label": "Tüm IF kayıtlarını görme",
        "group": "IF Yönetimi",
        "description": "Tüm IF kayıtlarını görüntüler.",
    },
    {
        "key": "if.delete",
        "label": "IF silme",
        "group": "IF Yönetimi",
        "description": "IF kayıtlarını silebilir.",
    },
    {
        "key": "if.approve_management",
        "label": "Yönetim Temsilcisi IF onayı",
        "group": "IF Yönetimi",
        "description": "IF yönetim temsilcisi onay adımını onaylar veya reddeder.",
    },
    {
        "key": "if.approve_deputy",
        "label": "Genel Müdür Yardımcısı IF onayı",
        "group": "IF Yönetimi",
        "description": "IF final onay adımını onaylar veya reddeder.",
    },
    {
        "key": "if.reject",
        "label": "IF reddetme",
        "group": "IF Yönetimi",
        "description": "Yetkili olduğu IF onay adımında ret sebebi girer.",
    },
    {
        "key": "risk.view",
        "label": "Riskleri görüntüleme",
        "group": "Risk Yönetimi",
        "description": "Risk yönetimi kayıtlarını ve RPN özetlerini görüntüler.",
    },
    {
        "key": "risk.manage",
        "label": "Risk yönetimi",
        "group": "Risk Yönetimi",
        "description": "Risk kaydı oluşturur, düzenler ve aksiyon/IF bağlantısı kurar.",
    },
    {
        "key": "risk.delete",
        "label": "Risk silme",
        "group": "Risk Yönetimi",
        "description": "Risk kayıtlarını silebilir.",
    },
    {
        "key": "fmea.view",
        "label": "FMEA görüntüleme",
        "group": "FMEA Analizi",
        "description": "FMEA kayıtlarını, RPN özetlerini ve bağlantılı aksiyonları görüntüler.",
    },
    {
        "key": "fmea.create",
        "label": "FMEA kaydı açma",
        "group": "FMEA Analizi",
        "description": "Yeni FMEA hata türü ve etkileri analizi kaydı oluşturur.",
    },
    {
        "key": "fmea.manage",
        "label": "FMEA yönetimi",
        "group": "FMEA Analizi",
        "description": "FMEA kayıtlarını düzenler, sorumlu, termin, puan ve bağlantıları yönetir.",
    },
    {
        "key": "fmea.close",
        "label": "FMEA kapatma",
        "group": "FMEA Analizi",
        "description": "FMEA kayıtlarını etkinlik kontrolü sonrası kapatır.",
    },
    {
        "key": "fmea.delete",
        "label": "FMEA arşivleme",
        "group": "FMEA Analizi",
        "description": "FMEA kayıtlarını denetim izi korunacak şekilde arşive alır.",
    },
    {
        "key": "fmea.export",
        "label": "FMEA raporu alma",
        "group": "FMEA Analizi",
        "description": "FMEA kayıtlarını rapor merkezinden dışa aktarır.",
    },
    {
        "key": "process.view",
        "label": "S\u00fcre\u00e7leri g\u00f6r\u00fcnt\u00fcleme",
        "group": "S\u00fcre\u00e7 Y\u00f6netimi",
        "description": "S\u00fcre\u00e7 kartlar\u0131n\u0131, ad\u0131mlar\u0131n\u0131 ve BPM haritas\u0131n\u0131 g\u00f6r\u00fcnt\u00fcler.",
    },
    {
        "key": "process.create",
        "label": "S\u00fcre\u00e7 olu\u015fturma",
        "group": "S\u00fcre\u00e7 Y\u00f6netimi",
        "description": "Yeni s\u00fcre\u00e7 kart\u0131 olu\u015fturur.",
    },
    {
        "key": "process.manage",
        "label": "S\u00fcre\u00e7 y\u00f6netimi",
        "group": "S\u00fcre\u00e7 Y\u00f6netimi",
        "description": "S\u00fcre\u00e7 kartlar\u0131n\u0131, ad\u0131mlar\u0131n\u0131 ve ba\u011flant\u0131lar\u0131n\u0131 y\u00f6netir.",
    },
    {
        "key": "process.delete",
        "label": "S\u00fcre\u00e7 ar\u015fivleme",
        "group": "S\u00fcre\u00e7 Y\u00f6netimi",
        "description": "S\u00fcre\u00e7 kartlar\u0131n\u0131 denetim izi korunacak \u015fekilde ar\u015five al\u0131r.",
    },
    {
        "key": "process.export",
        "label": "S\u00fcre\u00e7 raporu alma",
        "group": "S\u00fcre\u00e7 Y\u00f6netimi",
        "description": "S\u00fcre\u00e7 y\u00f6netimi kay\u0131tlar\u0131n\u0131 rapor merkezinden d\u0131\u015fa aktar\u0131r.",
    },
    {
        "key": "change_management.view",
        "label": "De\u011fi\u015fiklikleri g\u00f6r\u00fcnt\u00fcleme",
        "group": "De\u011fi\u015fiklik Y\u00f6netimi",
        "description": "De\u011fi\u015fiklik taleplerini, durumlar\u0131n\u0131 ve kan\u0131t dosyalar\u0131n\u0131 g\u00f6r\u00fcnt\u00fcler.",
    },
    {
        "key": "change_management.create",
        "label": "De\u011fi\u015fiklik talebi a\u00e7ma",
        "group": "De\u011fi\u015fiklik Y\u00f6netimi",
        "description": "Dok\u00fcman, proses, ekipman veya sistem i\u00e7in de\u011fi\u015fiklik talebi olu\u015fturur.",
    },
    {
        "key": "change_management.manage",
        "label": "De\u011fi\u015fiklik y\u00f6netimi",
        "group": "De\u011fi\u015fiklik Y\u00f6netimi",
        "description": "De\u011fi\u015fiklik kay\u0131tlar\u0131n\u0131 d\u00fczenler, sorumlu ve ba\u011flant\u0131lar\u0131 y\u00f6netir.",
    },
    {
        "key": "change_management.approve",
        "label": "De\u011fi\u015fiklik onay\u0131",
        "group": "De\u011fi\u015fiklik Y\u00f6netimi",
        "description": "De\u011fi\u015fiklik taleplerini onaylar, reddeder ve etkinlik kontrol\u00fcn\u00fc kapat\u0131r.",
    },
    {
        "key": "change_management.delete",
        "label": "De\u011fi\u015fiklik ar\u015fivleme",
        "group": "De\u011fi\u015fiklik Y\u00f6netimi",
        "description": "De\u011fi\u015fiklik kay\u0131tlar\u0131n\u0131 denetim izi korunacak \u015fekilde ar\u015five al\u0131r.",
    },
    {
        "key": "change_management.export",
        "label": "De\u011fi\u015fiklik raporu alma",
        "group": "De\u011fi\u015fiklik Y\u00f6netimi",
        "description": "De\u011fi\u015fiklik y\u00f6netimi kay\u0131tlar\u0131n\u0131 rapor merkezinden d\u0131\u015fa aktar\u0131r.",
    },
    {
        "key": "deviation.view",
        "label": "Sapma kay\u0131tlar\u0131n\u0131 g\u00f6r\u00fcnt\u00fcleme",
        "group": "Sapma / Uygunsuz \u00dcr\u00fcn",
        "description": "Sapma ve uygunsuz \u00fcr\u00fcn kay\u0131tlar\u0131n\u0131, kararlar\u0131 ve eklerini g\u00f6r\u00fcnt\u00fcler.",
    },
    {
        "key": "deviation.create",
        "label": "Sapma kayd\u0131 a\u00e7ma",
        "group": "Sapma / Uygunsuz \u00dcr\u00fcn",
        "description": "Yeni sapma veya uygunsuz \u00fcr\u00fcn kayd\u0131 olu\u015fturur.",
    },
    {
        "key": "deviation.manage",
        "label": "Sapma kay\u0131t y\u00f6netimi",
        "group": "Sapma / Uygunsuz \u00dcr\u00fcn",
        "description": "Sapma kay\u0131tlar\u0131n\u0131 d\u00fczenler, karantina, sorumlu ve ba\u011flant\u0131lar\u0131 y\u00f6netir.",
    },
    {
        "key": "deviation.approve",
        "label": "Sapma karar ve kapan\u0131\u015f onay\u0131",
        "group": "Sapma / Uygunsuz \u00dcr\u00fcn",
        "description": "Sapma karar\u0131 verir, etkinlik kontrol\u00fcn\u00fc kapat\u0131r ve kayd\u0131 sonu\u00e7land\u0131r\u0131r.",
    },
    {
        "key": "deviation.delete",
        "label": "Sapma ar\u015fivleme",
        "group": "Sapma / Uygunsuz \u00dcr\u00fcn",
        "description": "Sapma kay\u0131tlar\u0131n\u0131 denetim izi korunacak \u015fekilde ar\u015five al\u0131r.",
    },
    {
        "key": "deviation.export",
        "label": "Sapma raporu alma",
        "group": "Sapma / Uygunsuz \u00dcr\u00fcn",
        "description": "Sapma ve uygunsuz \u00fcr\u00fcn kay\u0131tlar\u0131n\u0131 rapor merkezinden d\u0131\u015fa aktar\u0131r.",
    },
    {
        "key": "incident.view",
        "label": "Olay / ramak kala g\u00f6r\u00fcnt\u00fcleme",
        "group": "Olay / Ramak Kala",
        "description": "Olay, ramak kala, tehlikeli durum ve kapan\u0131\u015f kay\u0131tlar\u0131n\u0131 g\u00f6r\u00fcnt\u00fcler.",
    },
    {
        "key": "incident.create",
        "label": "Olay / ramak kala bildirimi a\u00e7ma",
        "group": "Olay / Ramak Kala",
        "description": "Yeni olay, ramak kala veya tehlikeli durum bildirimi olu\u015fturur.",
    },
    {
        "key": "incident.manage",
        "label": "Olay / ramak kala y\u00f6netimi",
        "group": "Olay / Ramak Kala",
        "description": "Bildirimleri d\u00fczenler, inceleme bilgisi, sorumlu ve ba\u011flant\u0131lar\u0131 y\u00f6netir.",
    },
    {
        "key": "incident.review",
        "label": "Olay / ramak kala karar ve kapan\u0131\u015f",
        "group": "Olay / Ramak Kala",
        "description": "Bildirimleri incelemeye al\u0131r, karar verir ve etkinlik kontrol\u00fcn\u00fc kapat\u0131r.",
    },
    {
        "key": "incident.delete",
        "label": "Olay / ramak kala ar\u015fivleme",
        "group": "Olay / Ramak Kala",
        "description": "Olay ve ramak kala kay\u0131tlar\u0131n\u0131 denetim izi korunacak \u015fekilde ar\u015five al\u0131r.",
    },
    {
        "key": "incident.export",
        "label": "Olay / ramak kala raporu alma",
        "group": "Olay / Ramak Kala",
        "description": "Olay ve ramak kala kay\u0131tlar\u0131n\u0131 rapor merkezinden d\u0131\u015fa aktar\u0131r.",
    },
    {
        "key": "training.view",
        "label": "Eğitimleri görüntüleme",
        "group": "Eğitim / Yeterlilik",
        "description": "Atanan eğitimleri, doküman okuma onaylarını ve yeterlilik özetlerini görüntüler.",
    },
    {
        "key": "training.manage",
        "label": "Eğitim yönetimi",
        "group": "Eğitim / Yeterlilik",
        "description": "Eğitim kaydı oluşturur, katılımcı atar ve sonuçları günceller.",
    },
    {
        "key": "training.delete",
        "label": "Eğitim silme",
        "group": "Eğitim / Yeterlilik",
        "description": "Eğitim ve yeterlilik kayıtlarını silebilir.",
    },
    {
        "key": "complaints.view",
        "label": "Şikayetleri görüntüleme",
        "group": "Öneri & Şikayet",
        "description": "Müşteri şikayet kayıtlarını, terminleri ve bağlantılı aksiyon/IF kayıtlarını görüntüler.",
    },
    {
        "key": "complaints.manage",
        "label": "Şikayet yönetimi",
        "group": "Öneri & Şikayet",
        "description": "Şikayet kaydı oluşturur, düzenler, kök neden ve düzeltici faaliyetleri yönetir.",
    },
    {
        "key": "complaints.delete",
        "label": "Şikayet silme",
        "group": "Öneri & Şikayet",
        "description": "Şikayet kayıtlarını silebilir.",
    },
    {
        "key": "management_review.view",
        "label": "YGG görüntüleme",
        "group": "Yönetimin Gözden Geçirmesi",
        "description": "Yönetimin gözden geçirmesi toplantılarını, kararları ve çıktı raporlarını görüntüler.",
    },
    {
        "key": "management_review.manage",
        "label": "YGG yönetimi",
        "group": "Yönetimin Gözden Geçirmesi",
        "description": "YGG toplantı kaydı oluşturur, girdileri, kararları ve aksiyon bağlantılarını yönetir.",
    },
    {
        "key": "management_review.delete",
        "label": "YGG silme",
        "group": "Yönetimin Gözden Geçirmesi",
        "description": "Yönetimin gözden geçirmesi kayıtlarını silebilir.",
    },
    {
        "key": "suppliers.view",
        "label": "Tedarikçileri görüntüleme",
        "group": "Tedarikçi Değerlendirme",
        "description": "Tedarikçi kartlarını, değerlendirme puanlarını ve onay durumlarını görüntüler.",
    },
    {
        "key": "suppliers.evaluate",
        "label": "Tedarikçi değerlendirme",
        "group": "Tedarikçi Değerlendirme",
        "description": "Tedarikçilere dönemsel performans değerlendirmesi yapar.",
    },
    {
        "key": "suppliers.manage",
        "label": "Tedarikçi yönetimi",
        "group": "Tedarikçi Değerlendirme",
        "description": "Tedarikçi kartı oluşturur ve düzenler.",
    },
    {
        "key": "suppliers.delete",
        "label": "Tedarikçi pasife alma",
        "group": "Tedarikçi Değerlendirme",
        "description": "Tedarikçi kartlarını denetim izi korunacak şekilde pasife alır.",
    },
    {
        "key": "reports.view",
        "label": "Rapor merkezi görüntüleme",
        "group": "Rapor Merkezi",
        "description": "Modül bazlı denetim kanıtı ve yönetici özet raporlarını görüntüler.",
    },
    {
        "key": "reports.export",
        "label": "Rapor merkezi dışa aktarma",
        "group": "Rapor Merkezi",
        "description": "Rapor merkezindeki Excel çıktılarını indirir.",
    },
    {
        "key": "internal_audit.manage",
        "label": "İç denetim yönetimi",
        "group": "İç Denetim",
        "description": "İç denetim oluşturur, düzenler, kopyalar, siler ve cevaplar.",
    },
    {
        "key": "documents.view",
        "label": "Doküman görüntüleme",
        "group": "Doküman",
        "description": "Doküman listelerini, detaylarını, indirme ve önizleme alanlarını sadece görüntüler.",
    },
    {
        "key": "documents.manage",
        "label": "Doküman yönetimi",
        "group": "Doküman",
        "description": "Doküman yükler, düzenler, arşivler ve önizleme üretir.",
    },
    {
        "key": "documents.delete",
        "label": "Doküman silme",
        "group": "Doküman",
        "description": "Doküman kayıtlarını silebilir.",
    },
    {
        "key": "maintenance.inventory_manage",
        "label": "Bakım envanteri yönetimi",
        "group": "Bakım",
        "description": "Makine envanterini oluşturur, düzenler ve arşivler.",
    },
    {
        "key": "maintenance.fault_manage",
        "label": "Bakım arıza yönetimi",
        "group": "Bakım",
        "description": "Bakım arızalarını açar, düzenler, kapatır ve takip eder.",
    },
    {
        "key": "vehicles.view",
        "label": "Araçları görüntüleme",
        "group": "Araç Yönetimi",
        "description": "Araç envanterini, sigorta/muayene takiplerini ve işlem kayıtlarını görüntüler.",
    },
    {
        "key": "vehicles.manage",
        "label": "Araç yönetimi",
        "group": "Araç Yönetimi",
        "description": "Araç ekler, düzenler, siler; işlem ve akaryakıt kayıtlarını yönetir.",
    },
    {
        "key": "calibration.manage",
        "label": "Kalibrasyon planı yönetimi",
        "group": "Kalibrasyon Planı",
        "description": "Kalibrasyon kayıtlarını ekler, düzenler ve siler.",
    },
    {
        "key": "quality.create",
        "label": "Kalite deneyi açabilme",
        "group": "Kalite Deneyleri",
        "description": "Kalite deneyleri ekranında yeni deney kaydı oluşturur.",
    },
    {
        "key": "quality.parameters_manage",
        "label": "Kalite deney parametreleri",
        "group": "Kalite Deneyleri",
        "description": "Beton deney parametrelerini ve kabul aralıklarını yönetir.",
    },
    {
        "key": "organization.manage",
        "label": "Organizasyon şeması yönetimi",
        "group": "Organizasyon",
        "description": "Organizasyon şeması kişi/departman kutularını yönetir.",
    },
)

DEFAULT_COMPANIES = (
    {
        "code": "000",
        "package_key": "iso_core",
        "is_demo": True,
        "name": "Deneme Hesabı",
    },
    {
        "code": "001",
        "package_key": "production_plus",
        "is_demo": False,
        "name": "Er Prefabrik",
    },
)
PRIMARY_COMPANY_CODE = "001"

ROLE_DEFINITIONS = (
    {
        "key": "super_admin",
        "name": "Süper Admin",
        "hierarchy_level": 1,
        "description": "Sistemin en yüksek rolüdür. Tüm izinlere sahiptir ve rol ataması yapabilir.",
        "permissions": [item["key"] for item in PERMISSION_CATALOG],
    },
    {
        "key": "management_representative",
        "name": "Yönetim Temsilcisi",
        "hierarchy_level": 10,
        "description": "Kalite sistemi süreçlerini, aksiyon kapanışlarını, IF yönetim onaylarını ve denetimleri yönetir.",
        "permissions": [
            "iso_dashboard.view",
            "management_due_dashboard.view",
            "users.manage",
            "actions.create",
            "actions.edit",
            "actions.delete",
            "actions.comment_assigned",
            "actions.request_close_assigned",
            "actions.approve_closure",
            "actions.view_all",
            "if.view_all",
            "if.delete",
            "if.approve_management",
            "if.reject",
            "risk.view",
            "risk.manage",
            "risk.delete",
            "fmea.view",
            "fmea.create",
            "fmea.manage",
            "fmea.close",
            "fmea.delete",
            "fmea.export",
            "process.view",
            "process.create",
            "process.manage",
            "process.delete",
            "process.export",
            "change_management.view",
            "change_management.create",
            "change_management.manage",
            "change_management.approve",
            "change_management.delete",
            "change_management.export",
            "deviation.view",
            "deviation.create",
            "deviation.manage",
            "deviation.approve",
            "deviation.delete",
            "deviation.export",
            "incident.view",
            "incident.create",
            "incident.manage",
            "incident.review",
            "incident.delete",
            "incident.export",
            "training.view",
            "training.manage",
            "training.delete",
            "complaints.view",
            "complaints.manage",
            "complaints.delete",
            "management_review.view",
            "management_review.manage",
            "management_review.delete",
            "suppliers.view",
            "suppliers.evaluate",
            "suppliers.manage",
            "suppliers.delete",
            "reports.view",
            "reports.export",
            "internal_audit.manage",
            "documents.manage",
            "documents.delete",
            "maintenance.inventory_manage",
            "maintenance.fault_manage",
            "vehicles.view",
            "vehicles.manage",
            "calibration.manage",
            "quality.parameters_manage",
            "organization.manage",
        ],
    },
    {
        "key": "management",
        "name": "Yönetim",
        "hierarchy_level": 20,
        "description": "Yönetim seviyesinde aksiyonları ve IF kayıtlarını görüntüler, yetkili onayları verir.",
        "permissions": [
            "iso_dashboard.view",
            "management_due_dashboard.view",
            "if.view_all",
            "if.approve_deputy",
            "if.reject",
            "actions.view_all",
            "documents.view",
            "risk.view",
            "fmea.view",
            "fmea.export",
            "process.view",
            "process.export",
            "change_management.view",
            "change_management.approve",
            "change_management.export",
            "deviation.view",
            "deviation.approve",
            "deviation.export",
            "incident.view",
            "incident.review",
            "incident.export",
            "training.view",
            "complaints.view",
            "management_review.view",
            "management_review.manage",
            "suppliers.view",
            "reports.view",
            "reports.export",
            "vehicles.view",
        ],
    },
    {
        "key": "department_manager",
        "name": "Departman Yöneticisi",
        "hierarchy_level": 30,
        "description": "Kendi departmanı ve sorumluluğundaki işler için aksiyon ve görev takibi yapar.",
        "permissions": [
            "management_due_dashboard.view",
            "actions.create",
            "actions.comment_assigned",
            "actions.request_close_assigned",
            "maintenance.fault_manage",
            "documents.view",
            "risk.view",
            "fmea.view",
            "fmea.create",
            "fmea.manage",
            "process.view",
            "process.create",
            "process.manage",
            "change_management.view",
            "change_management.create",
            "deviation.view",
            "deviation.create",
            "deviation.manage",
            "incident.view",
            "incident.create",
            "incident.manage",
            "training.view",
            "complaints.view",
            "complaints.manage",
            "management_review.view",
            "suppliers.view",
            "suppliers.evaluate",
            "reports.view",
            "quality.create",
            "vehicles.view",
            "vehicles.manage",
        ],
    },
    {
        "key": "department_staff",
        "name": "Departman Personeli",
        "hierarchy_level": 40,
        "description": "Kendisine atanan aksiyon ve görevlerde yorum, kanıt ve kapanış talebi işlemleri yapar.",
        "permissions": [
            "actions.comment_assigned",
            "actions.request_close_assigned",
            "documents.view",
            "fmea.view",
            "fmea.create",
            "process.view",
            "change_management.view",
            "change_management.create",
            "deviation.view",
            "deviation.create",
            "incident.view",
            "incident.create",
            "training.view",
            "complaints.view",
            "suppliers.view",
            "vehicles.view",
        ],
    },
    {
        "key": "viewer",
        "name": "Sadece Görüntüleyici",
        "hierarchy_level": 50,
        "description": "Yetkili olduğu sayfaları sadece görüntüler.",
        "permissions": [
            "documents.view",
            "fmea.view",
            "process.view",
            "change_management.view",
            "deviation.view",
            "incident.view",
            "training.view",
            "complaints.view",
            "suppliers.view",
            "vehicles.view",
        ],
    },
)

REMOVED_ROLE_MAPPINGS = {
    "executive_approver": "management",
    "module_responsible": "department_staff",
    "task_responsible": "department_staff",
    "audited_viewer": "department_staff",
}


DEFAULT_USERS = (
    {
        "username": "superadmin",
        "full_name": "Süper Admin",
        "title": "Sistem Sahibi",
        "email": "",
        "password": "0408169635",
        "roles": ("super_admin",),
        "permissions": {
            "can_create_actions": True,
            "can_edit_actions": True,
            "can_delete_actions": True,
            "can_comment_assigned_actions": True,
            "can_close_assigned_actions": True,
            "can_manage_users": True,
        },
    },
    {
        "username": "oguzhan",
        "full_name": "Oğuzhan Gökgönül",
        "title": "Yönetim Temsilcisi",
        "email": "oguzhangokgonul@erprefabrik.com.tr",
        "password": "kysoguzhan",
        "roles": ("management_representative",),
        "permissions": {
            "can_create_actions": True,
            "can_edit_actions": True,
            "can_delete_actions": True,
            "can_comment_assigned_actions": True,
            "can_close_assigned_actions": True,
            "can_manage_users": True,
        },
    },
    {
        "username": "ufuk",
        "full_name": "Ufuk Yaşayan",
        "title": "Prefabrik Proje Müdürü",
        "email": "",
        "password": "kysufuk",
        "roles": ("department_staff",),
        "permissions": {
            "can_create_actions": False,
            "can_edit_actions": False,
            "can_delete_actions": False,
            "can_comment_assigned_actions": True,
            "can_close_assigned_actions": True,
            "can_manage_users": False,
        },
    },
    {
        "username": "seyma",
        "full_name": "Şeyma İnci Göçmen",
        "title": "Proje Sorumlusu",
        "email": "seymainci@erprefabrik.com.tr",
        "password": "kysseyma",
        "roles": ("department_staff",),
        "permissions": {
            "can_create_actions": False,
            "can_edit_actions": False,
            "can_delete_actions": False,
            "can_comment_assigned_actions": True,
            "can_close_assigned_actions": True,
            "can_manage_users": False,
        },
    },
    {
        "username": "turgut",
        "full_name": "Turgut Özal Pekyılmaz",
        "title": "Şantiye Peygamberi",
        "email": "turgutpekyilmaz@erprefabrik.com.tr",
        "password": "kysturgut",
        "roles": ("department_staff",),
        "permissions": {
            "can_create_actions": False,
            "can_edit_actions": False,
            "can_delete_actions": False,
            "can_comment_assigned_actions": True,
            "can_close_assigned_actions": True,
            "can_manage_users": False,
        },
    },
)

ADMIN_USERNAMES = {"superadmin"}
DEFAULT_ROLE_ASSIGNMENT_MARKER = "default_role_assignments_initialized"
LEGACY_PERMISSION_FIELD_MAP = {
    "can_create_actions": "actions.create",
    "can_edit_actions": "actions.edit",
    "can_delete_actions": "actions.delete",
    "can_comment_assigned_actions": "actions.comment_assigned",
    "can_close_assigned_actions": "actions.request_close_assigned",
    "can_manage_users": "users.manage",
}


def sync_seed_legacy_permissions(user):
    permission_keys = {
        permission.permission_key
        for role in user.roles
        for permission in role.permissions
    }
    if any(role.key == "super_admin" for role in user.roles):
        permission_keys.update(item["key"] for item in PERMISSION_CATALOG)
    for field, permission_key in LEGACY_PERMISSION_FIELD_MAP.items():
        setattr(user, field, permission_key in permission_keys)


def ensure_runtime_schema():
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    changed = False

    if "users" in tables:
        columns = {column["name"] for column in inspector.get_columns("users")}
        if "email" not in columns:
            db.session.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(255)"))
            changed = True
        if "personnel_contact_id" not in columns:
            db.session.execute(
                text("ALTER TABLE users ADD COLUMN personnel_contact_id INTEGER")
            )
            changed = True
        db.session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_users_personnel_contact_id "
                "ON users (personnel_contact_id)"
            )
        )

    if "app_settings" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE app_settings (
                    key VARCHAR(80) NOT NULL PRIMARY KEY,
                    value VARCHAR(255) NOT NULL
                )
                """
            )
        )
        changed = True
        tables.add("app_settings")

    if "audit_logs" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE audit_logs (
                    id INTEGER NOT NULL PRIMARY KEY,
                    company_id INTEGER,
                    user_id INTEGER,
                    entity_type VARCHAR(120) NOT NULL,
                    entity_id VARCHAR(80),
                    action VARCHAR(40) NOT NULL,
                    summary VARCHAR(255),
                    old_values TEXT,
                    new_values TEXT,
                    ip_address VARCHAR(80),
                    user_agent VARCHAR(255),
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(company_id) REFERENCES companies (id),
                    FOREIGN KEY(user_id) REFERENCES users (id)
                )
                """
            )
        )
        changed = True
        tables.add("audit_logs")

    if "audit_logs" in tables:
        for index_name, column_name in (
            ("ix_audit_logs_company_id", "company_id"),
            ("ix_audit_logs_user_id", "user_id"),
            ("ix_audit_logs_entity_type", "entity_type"),
            ("ix_audit_logs_entity_id", "entity_id"),
            ("ix_audit_logs_action", "action"),
            ("ix_audit_logs_created_at", "created_at"),
        ):
            db.session.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON audit_logs ({column_name})"
                )
            )

    if "companies" in tables:
        columns = {column["name"] for column in inspector.get_columns("companies")}
        company_columns = {
            "package_key": (
                "ALTER TABLE companies "
                "ADD COLUMN package_key VARCHAR(40) NOT NULL DEFAULT 'production_plus'"
            ),
            "is_demo": (
                "ALTER TABLE companies "
                "ADD COLUMN is_demo BOOLEAN NOT NULL DEFAULT 0"
            ),
            "logo_file_path": "ALTER TABLE companies ADD COLUMN logo_file_path VARCHAR(500)",
            "logo_original_name": "ALTER TABLE companies ADD COLUMN logo_original_name VARCHAR(255)",
            "brand_primary_color": "ALTER TABLE companies ADD COLUMN brand_primary_color VARCHAR(7)",
            "brand_accent_color": "ALTER TABLE companies ADD COLUMN brand_accent_color VARCHAR(7)",
            "user_limit": "ALTER TABLE companies ADD COLUMN user_limit INTEGER DEFAULT 25",
            "storage_quota_mb": "ALTER TABLE companies ADD COLUMN storage_quota_mb INTEGER DEFAULT 1024",
        }
        for column_name, statement in company_columns.items():
            if column_name not in columns:
                db.session.execute(text(statement))
                changed = True

    if "company_departments" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE company_departments (
                    id INTEGER NOT NULL PRIMARY KEY,
                    company_id INTEGER NOT NULL,
                    name VARCHAR(160) NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(company_id) REFERENCES companies (id)
                )
                """
            )
        )
        changed = True
        tables.add("company_departments")

    if "company_departments" in tables:
        columns = {
            column["name"] for column in inspector.get_columns("company_departments")
        }
        department_columns = {
            "company_id": "ALTER TABLE company_departments ADD COLUMN company_id INTEGER NOT NULL DEFAULT 0",
            "name": "ALTER TABLE company_departments ADD COLUMN name VARCHAR(160) NOT NULL DEFAULT ''",
            "sort_order": "ALTER TABLE company_departments ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0",
            "is_active": "ALTER TABLE company_departments ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1",
            "created_at": "ALTER TABLE company_departments ADD COLUMN created_at DATETIME",
            "updated_at": "ALTER TABLE company_departments ADD COLUMN updated_at DATETIME",
        }
        for column_name, statement in department_columns.items():
            if column_name not in columns:
                db.session.execute(text(statement))
                changed = True
        db.session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_company_departments_company_id "
                "ON company_departments (company_id)"
            )
        )
        db.session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_company_departments_company_name "
                "ON company_departments (company_id, name)"
            )
        )

    if "pilot_programs" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE pilot_programs (
                    id INTEGER NOT NULL PRIMARY KEY,
                    company_id INTEGER NOT NULL,
                    status VARCHAR(40) NOT NULL DEFAULT 'planned',
                    contact_name VARCHAR(160),
                    contact_phone VARCHAR(80),
                    contact_email VARCHAR(255),
                    start_date DATE,
                    end_date DATE,
                    target_modules TEXT,
                    success_criteria TEXT,
                    feedback_summary TEXT,
                    sales_blocker BOOLEAN NOT NULL DEFAULT 0,
                    sales_blocker_note TEXT,
                    next_follow_up_date DATE,
                    result VARCHAR(160),
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(company_id) REFERENCES companies (id)
                )
                """
            )
        )
        changed = True
        tables.add("pilot_programs")

    if "pilot_programs" in tables:
        columns = {column["name"] for column in inspector.get_columns("pilot_programs")}
        pilot_columns = {
            "company_id": "ALTER TABLE pilot_programs ADD COLUMN company_id INTEGER NOT NULL DEFAULT 0",
            "status": "ALTER TABLE pilot_programs ADD COLUMN status VARCHAR(40) NOT NULL DEFAULT 'planned'",
            "contact_name": "ALTER TABLE pilot_programs ADD COLUMN contact_name VARCHAR(160)",
            "contact_phone": "ALTER TABLE pilot_programs ADD COLUMN contact_phone VARCHAR(80)",
            "contact_email": "ALTER TABLE pilot_programs ADD COLUMN contact_email VARCHAR(255)",
            "start_date": "ALTER TABLE pilot_programs ADD COLUMN start_date DATE",
            "end_date": "ALTER TABLE pilot_programs ADD COLUMN end_date DATE",
            "target_modules": "ALTER TABLE pilot_programs ADD COLUMN target_modules TEXT",
            "success_criteria": "ALTER TABLE pilot_programs ADD COLUMN success_criteria TEXT",
            "feedback_summary": "ALTER TABLE pilot_programs ADD COLUMN feedback_summary TEXT",
            "sales_blocker": "ALTER TABLE pilot_programs ADD COLUMN sales_blocker BOOLEAN NOT NULL DEFAULT 0",
            "sales_blocker_note": "ALTER TABLE pilot_programs ADD COLUMN sales_blocker_note TEXT",
            "next_follow_up_date": "ALTER TABLE pilot_programs ADD COLUMN next_follow_up_date DATE",
            "result": "ALTER TABLE pilot_programs ADD COLUMN result VARCHAR(160)",
            "created_at": "ALTER TABLE pilot_programs ADD COLUMN created_at DATETIME",
            "updated_at": "ALTER TABLE pilot_programs ADD COLUMN updated_at DATETIME",
        }
        for column_name, statement in pilot_columns.items():
            if column_name not in columns:
                db.session.execute(text(statement))
                changed = True
        for index_name, column_name in (
            ("ix_pilot_programs_company_id", "company_id"),
            ("ix_pilot_programs_status", "status"),
            ("ix_pilot_programs_next_follow_up_date", "next_follow_up_date"),
        ):
            db.session.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON pilot_programs ({column_name})"
                )
            )

    if "notifications" in tables:
        columns = {column["name"] for column in inspector.get_columns("notifications")}
        notification_columns = {
            "dof_id": "ALTER TABLE notifications ADD COLUMN dof_id INTEGER",
            "document_revision_request_id": (
                "ALTER TABLE notifications ADD COLUMN document_revision_request_id INTEGER"
            ),
            "notification_type": (
                "ALTER TABLE notifications "
                "ADD COLUMN notification_type VARCHAR(40) NOT NULL DEFAULT 'info'"
            ),
            "source_key": "ALTER TABLE notifications ADD COLUMN source_key VARCHAR(180)",
            "target_url": "ALTER TABLE notifications ADD COLUMN target_url VARCHAR(500)",
            "due_date": "ALTER TABLE notifications ADD COLUMN due_date DATE",
            "email_sent_at": "ALTER TABLE notifications ADD COLUMN email_sent_at DATETIME",
        }
        for column_name, statement in notification_columns.items():
            if column_name not in columns:
                db.session.execute(text(statement))
                changed = True
        for index_name, column_name in (
            ("ix_notifications_company_id", "company_id"),
            ("ix_notifications_user_id", "user_id"),
            ("ix_notifications_source_key", "source_key"),
            ("ix_notifications_due_date", "due_date"),
        ):
            db.session.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON notifications ({column_name})"
                )
            )

    if "risk_records" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE risk_records (
                    id INTEGER NOT NULL PRIMARY KEY,
                    company_id INTEGER,
                    risk_no VARCHAR(30) NOT NULL,
                    title VARCHAR(180) NOT NULL,
                    department VARCHAR(80),
                    process VARCHAR(160),
                    description TEXT,
                    cause TEXT,
                    consequence TEXT,
                    likelihood INTEGER NOT NULL DEFAULT 1,
                    severity INTEGER NOT NULL DEFAULT 1,
                    status VARCHAR(40) NOT NULL DEFAULT 'Açık',
                    due_date DATE,
                    owner_user_id INTEGER,
                    action_id INTEGER,
                    dof_id INTEGER,
                    created_by_user_id INTEGER,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(company_id) REFERENCES companies (id),
                    FOREIGN KEY(owner_user_id) REFERENCES users (id),
                    FOREIGN KEY(action_id) REFERENCES actions (id),
                    FOREIGN KEY(dof_id) REFERENCES dofs (id),
                    FOREIGN KEY(created_by_user_id) REFERENCES users (id)
                )
                """
            )
        )
        changed = True
        tables.add("risk_records")

    if "risk_records" in tables:
        for index_name, column_name in (
            ("ix_risk_records_company_id", "company_id"),
            ("ix_risk_records_owner_user_id", "owner_user_id"),
            ("ix_risk_records_action_id", "action_id"),
            ("ix_risk_records_dof_id", "dof_id"),
        ):
            db.session.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON risk_records ({column_name})"
                )
            )
        db.session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_risk_records_company_risk_no "
                "ON risk_records (company_id, risk_no)"
            )
        )

    if "fmea_records" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE fmea_records (
                    id INTEGER NOT NULL PRIMARY KEY,
                    company_id INTEGER,
                    fmea_no VARCHAR(40) NOT NULL,
                    process_name VARCHAR(160) NOT NULL,
                    product_or_service VARCHAR(180),
                    operation_step VARCHAR(180),
                    failure_mode VARCHAR(180) NOT NULL,
                    failure_effect TEXT,
                    failure_cause TEXT,
                    current_controls TEXT,
                    severity INTEGER NOT NULL DEFAULT 1,
                    occurrence INTEGER NOT NULL DEFAULT 1,
                    detection INTEGER NOT NULL DEFAULT 1,
                    recommended_action TEXT,
                    due_date DATE,
                    closed_at DATE,
                    status VARCHAR(40) NOT NULL DEFAULT 'Açık',
                    responsible_user_id INTEGER,
                    action_id INTEGER,
                    risk_id INTEGER,
                    dof_id INTEGER,
                    incident_id INTEGER,
                    deviation_id INTEGER,
                    created_by_user_id INTEGER,
                    archived_at DATETIME,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(company_id) REFERENCES companies (id),
                    FOREIGN KEY(responsible_user_id) REFERENCES users (id),
                    FOREIGN KEY(action_id) REFERENCES actions (id),
                    FOREIGN KEY(risk_id) REFERENCES risk_records (id),
                    FOREIGN KEY(dof_id) REFERENCES dofs (id),
                    FOREIGN KEY(incident_id) REFERENCES incident_reports (id),
                    FOREIGN KEY(deviation_id) REFERENCES deviation_records (id),
                    FOREIGN KEY(created_by_user_id) REFERENCES users (id)
                )
                """
            )
        )
        changed = True
        tables.add("fmea_records")

    if "fmea_records" in tables:
        columns = {column["name"] for column in inspector.get_columns("fmea_records")}
        fmea_columns = {
            "company_id": "ALTER TABLE fmea_records ADD COLUMN company_id INTEGER",
            "fmea_no": "ALTER TABLE fmea_records ADD COLUMN fmea_no VARCHAR(40) NOT NULL DEFAULT ''",
            "process_name": "ALTER TABLE fmea_records ADD COLUMN process_name VARCHAR(160) NOT NULL DEFAULT ''",
            "product_or_service": "ALTER TABLE fmea_records ADD COLUMN product_or_service VARCHAR(180)",
            "operation_step": "ALTER TABLE fmea_records ADD COLUMN operation_step VARCHAR(180)",
            "failure_mode": "ALTER TABLE fmea_records ADD COLUMN failure_mode VARCHAR(180) NOT NULL DEFAULT ''",
            "failure_effect": "ALTER TABLE fmea_records ADD COLUMN failure_effect TEXT",
            "failure_cause": "ALTER TABLE fmea_records ADD COLUMN failure_cause TEXT",
            "current_controls": "ALTER TABLE fmea_records ADD COLUMN current_controls TEXT",
            "severity": "ALTER TABLE fmea_records ADD COLUMN severity INTEGER NOT NULL DEFAULT 1",
            "occurrence": "ALTER TABLE fmea_records ADD COLUMN occurrence INTEGER NOT NULL DEFAULT 1",
            "detection": "ALTER TABLE fmea_records ADD COLUMN detection INTEGER NOT NULL DEFAULT 1",
            "recommended_action": "ALTER TABLE fmea_records ADD COLUMN recommended_action TEXT",
            "due_date": "ALTER TABLE fmea_records ADD COLUMN due_date DATE",
            "closed_at": "ALTER TABLE fmea_records ADD COLUMN closed_at DATE",
            "status": "ALTER TABLE fmea_records ADD COLUMN status VARCHAR(40) NOT NULL DEFAULT 'Açık'",
            "responsible_user_id": "ALTER TABLE fmea_records ADD COLUMN responsible_user_id INTEGER",
            "action_id": "ALTER TABLE fmea_records ADD COLUMN action_id INTEGER",
            "risk_id": "ALTER TABLE fmea_records ADD COLUMN risk_id INTEGER",
            "dof_id": "ALTER TABLE fmea_records ADD COLUMN dof_id INTEGER",
            "incident_id": "ALTER TABLE fmea_records ADD COLUMN incident_id INTEGER",
            "deviation_id": "ALTER TABLE fmea_records ADD COLUMN deviation_id INTEGER",
            "created_by_user_id": "ALTER TABLE fmea_records ADD COLUMN created_by_user_id INTEGER",
            "archived_at": "ALTER TABLE fmea_records ADD COLUMN archived_at DATETIME",
            "created_at": "ALTER TABLE fmea_records ADD COLUMN created_at DATETIME",
            "updated_at": "ALTER TABLE fmea_records ADD COLUMN updated_at DATETIME",
        }
        for column_name, statement in fmea_columns.items():
            if column_name not in columns:
                db.session.execute(text(statement))
                changed = True
        for index_name, column_name in (
            ("ix_fmea_records_company_id", "company_id"),
            ("ix_fmea_records_fmea_no", "fmea_no"),
            ("ix_fmea_records_status", "status"),
            ("ix_fmea_records_due_date", "due_date"),
            ("ix_fmea_records_responsible_user_id", "responsible_user_id"),
            ("ix_fmea_records_action_id", "action_id"),
            ("ix_fmea_records_risk_id", "risk_id"),
        ):
            db.session.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON fmea_records ({column_name})"
                )
            )
        db.session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_fmea_records_company_fmea_no "
                "ON fmea_records (company_id, fmea_no)"
            )
        )

    if "process_records" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE process_records (
                    id INTEGER NOT NULL PRIMARY KEY,
                    company_id INTEGER,
                    process_no VARCHAR(40) NOT NULL,
                    title VARCHAR(180) NOT NULL,
                    category VARCHAR(60) NOT NULL DEFAULT 'Ana S\u00fcre\u00e7',
                    owner_user_id INTEGER,
                    department VARCHAR(80),
                    purpose TEXT,
                    scope TEXT,
                    inputs TEXT,
                    outputs TEXT,
                    suppliers TEXT,
                    customers TEXT,
                    kpi TEXT,
                    review_frequency VARCHAR(80),
                    next_review_date DATE,
                    related_document_id INTEGER,
                    risk_id INTEGER,
                    action_id INTEGER,
                    status VARCHAR(40) NOT NULL DEFAULT 'Taslak',
                    created_by_user_id INTEGER,
                    archived_at DATETIME,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(company_id) REFERENCES companies (id),
                    FOREIGN KEY(owner_user_id) REFERENCES users (id),
                    FOREIGN KEY(related_document_id) REFERENCES documents (id),
                    FOREIGN KEY(risk_id) REFERENCES risk_records (id),
                    FOREIGN KEY(action_id) REFERENCES actions (id),
                    FOREIGN KEY(created_by_user_id) REFERENCES users (id)
                )
                """
            )
        )
        changed = True
        tables.add("process_records")

    if "process_records" in tables:
        columns = {column["name"] for column in inspector.get_columns("process_records")}
        process_columns = {
            "company_id": "ALTER TABLE process_records ADD COLUMN company_id INTEGER",
            "process_no": "ALTER TABLE process_records ADD COLUMN process_no VARCHAR(40) NOT NULL DEFAULT ''",
            "title": "ALTER TABLE process_records ADD COLUMN title VARCHAR(180) NOT NULL DEFAULT ''",
            "category": "ALTER TABLE process_records ADD COLUMN category VARCHAR(60) NOT NULL DEFAULT 'Ana S\u00fcre\u00e7'",
            "owner_user_id": "ALTER TABLE process_records ADD COLUMN owner_user_id INTEGER",
            "department": "ALTER TABLE process_records ADD COLUMN department VARCHAR(80)",
            "purpose": "ALTER TABLE process_records ADD COLUMN purpose TEXT",
            "scope": "ALTER TABLE process_records ADD COLUMN scope TEXT",
            "inputs": "ALTER TABLE process_records ADD COLUMN inputs TEXT",
            "outputs": "ALTER TABLE process_records ADD COLUMN outputs TEXT",
            "suppliers": "ALTER TABLE process_records ADD COLUMN suppliers TEXT",
            "customers": "ALTER TABLE process_records ADD COLUMN customers TEXT",
            "kpi": "ALTER TABLE process_records ADD COLUMN kpi TEXT",
            "review_frequency": "ALTER TABLE process_records ADD COLUMN review_frequency VARCHAR(80)",
            "next_review_date": "ALTER TABLE process_records ADD COLUMN next_review_date DATE",
            "related_document_id": "ALTER TABLE process_records ADD COLUMN related_document_id INTEGER",
            "risk_id": "ALTER TABLE process_records ADD COLUMN risk_id INTEGER",
            "action_id": "ALTER TABLE process_records ADD COLUMN action_id INTEGER",
            "status": "ALTER TABLE process_records ADD COLUMN status VARCHAR(40) NOT NULL DEFAULT 'Taslak'",
            "created_by_user_id": "ALTER TABLE process_records ADD COLUMN created_by_user_id INTEGER",
            "archived_at": "ALTER TABLE process_records ADD COLUMN archived_at DATETIME",
            "created_at": "ALTER TABLE process_records ADD COLUMN created_at DATETIME",
            "updated_at": "ALTER TABLE process_records ADD COLUMN updated_at DATETIME",
        }
        for column_name, statement in process_columns.items():
            if column_name not in columns:
                db.session.execute(text(statement))
                changed = True
        for index_name, column_name in (
            ("ix_process_records_company_id", "company_id"),
            ("ix_process_records_process_no", "process_no"),
            ("ix_process_records_status", "status"),
            ("ix_process_records_category", "category"),
            ("ix_process_records_owner_user_id", "owner_user_id"),
            ("ix_process_records_next_review_date", "next_review_date"),
        ):
            db.session.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON process_records ({column_name})"
                )
            )
        db.session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_process_records_company_process_no "
                "ON process_records (company_id, process_no)"
            )
        )

    if "process_steps" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE process_steps (
                    id INTEGER NOT NULL PRIMARY KEY,
                    company_id INTEGER,
                    process_id INTEGER NOT NULL,
                    step_order INTEGER NOT NULL DEFAULT 1,
                    title VARCHAR(180) NOT NULL,
                    responsible_user_id INTEGER,
                    description TEXT,
                    input_note TEXT,
                    output_note TEXT,
                    control_point TEXT,
                    document_id INTEGER,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(company_id) REFERENCES companies (id),
                    FOREIGN KEY(process_id) REFERENCES process_records (id),
                    FOREIGN KEY(responsible_user_id) REFERENCES users (id),
                    FOREIGN KEY(document_id) REFERENCES documents (id)
                )
                """
            )
        )
        changed = True
        tables.add("process_steps")

    if "process_steps" in tables:
        columns = {column["name"] for column in inspector.get_columns("process_steps")}
        process_step_columns = {
            "company_id": "ALTER TABLE process_steps ADD COLUMN company_id INTEGER",
            "process_id": "ALTER TABLE process_steps ADD COLUMN process_id INTEGER NOT NULL DEFAULT 0",
            "step_order": "ALTER TABLE process_steps ADD COLUMN step_order INTEGER NOT NULL DEFAULT 1",
            "title": "ALTER TABLE process_steps ADD COLUMN title VARCHAR(180) NOT NULL DEFAULT ''",
            "responsible_user_id": "ALTER TABLE process_steps ADD COLUMN responsible_user_id INTEGER",
            "description": "ALTER TABLE process_steps ADD COLUMN description TEXT",
            "input_note": "ALTER TABLE process_steps ADD COLUMN input_note TEXT",
            "output_note": "ALTER TABLE process_steps ADD COLUMN output_note TEXT",
            "control_point": "ALTER TABLE process_steps ADD COLUMN control_point TEXT",
            "document_id": "ALTER TABLE process_steps ADD COLUMN document_id INTEGER",
            "created_at": "ALTER TABLE process_steps ADD COLUMN created_at DATETIME",
            "updated_at": "ALTER TABLE process_steps ADD COLUMN updated_at DATETIME",
        }
        for column_name, statement in process_step_columns.items():
            if column_name not in columns:
                db.session.execute(text(statement))
                changed = True
        for index_name, column_name in (
            ("ix_process_steps_company_id", "company_id"),
            ("ix_process_steps_process_id", "process_id"),
            ("ix_process_steps_step_order", "step_order"),
            ("ix_process_steps_responsible_user_id", "responsible_user_id"),
            ("ix_process_steps_document_id", "document_id"),
        ):
            db.session.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON process_steps ({column_name})"
                )
            )

    if "process_relations" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE process_relations (
                    id INTEGER NOT NULL PRIMARY KEY,
                    company_id INTEGER,
                    source_process_id INTEGER NOT NULL,
                    target_process_id INTEGER NOT NULL,
                    relation_type VARCHAR(60) NOT NULL DEFAULT 'Ba\u011flant\u0131l\u0131 S\u00fcre\u00e7',
                    description TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(company_id) REFERENCES companies (id),
                    FOREIGN KEY(source_process_id) REFERENCES process_records (id),
                    FOREIGN KEY(target_process_id) REFERENCES process_records (id)
                )
                """
            )
        )
        changed = True
        tables.add("process_relations")

    if "process_relations" in tables:
        columns = {column["name"] for column in inspector.get_columns("process_relations")}
        process_relation_columns = {
            "company_id": "ALTER TABLE process_relations ADD COLUMN company_id INTEGER",
            "source_process_id": "ALTER TABLE process_relations ADD COLUMN source_process_id INTEGER NOT NULL DEFAULT 0",
            "target_process_id": "ALTER TABLE process_relations ADD COLUMN target_process_id INTEGER NOT NULL DEFAULT 0",
            "relation_type": "ALTER TABLE process_relations ADD COLUMN relation_type VARCHAR(60) NOT NULL DEFAULT 'Ba\u011flant\u0131l\u0131 S\u00fcre\u00e7'",
            "description": "ALTER TABLE process_relations ADD COLUMN description TEXT",
            "created_at": "ALTER TABLE process_relations ADD COLUMN created_at DATETIME",
            "updated_at": "ALTER TABLE process_relations ADD COLUMN updated_at DATETIME",
        }
        for column_name, statement in process_relation_columns.items():
            if column_name not in columns:
                db.session.execute(text(statement))
                changed = True
        for index_name, column_name in (
            ("ix_process_relations_company_id", "company_id"),
            ("ix_process_relations_source_process_id", "source_process_id"),
            ("ix_process_relations_target_process_id", "target_process_id"),
            ("ix_process_relations_relation_type", "relation_type"),
        ):
            db.session.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON process_relations ({column_name})"
                )
            )

    if "change_requests" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE change_requests (
                    id INTEGER NOT NULL PRIMARY KEY,
                    company_id INTEGER,
                    change_no VARCHAR(40) NOT NULL,
                    title VARCHAR(180) NOT NULL,
                    change_type VARCHAR(60) NOT NULL DEFAULT 'Proses',
                    description TEXT,
                    reason TEXT,
                    scope TEXT,
                    department VARCHAR(80),
                    process_name VARCHAR(160),
                    risk_level VARCHAR(40) NOT NULL DEFAULT 'Orta',
                    status VARCHAR(40) NOT NULL DEFAULT 'Onay Bekliyor',
                    planned_date DATE,
                    due_date DATE,
                    effective_date DATE,
                    requester_user_id INTEGER,
                    responsible_user_id INTEGER,
                    approver_user_id INTEGER,
                    document_id INTEGER,
                    action_id INTEGER,
                    risk_id INTEGER,
                    dof_id INTEGER,
                    approval_note TEXT,
                    implementation_note TEXT,
                    effectiveness_note TEXT,
                    created_by_user_id INTEGER,
                    archived_at DATETIME,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(company_id) REFERENCES companies (id),
                    FOREIGN KEY(requester_user_id) REFERENCES users (id),
                    FOREIGN KEY(responsible_user_id) REFERENCES users (id),
                    FOREIGN KEY(approver_user_id) REFERENCES users (id),
                    FOREIGN KEY(document_id) REFERENCES documents (id),
                    FOREIGN KEY(action_id) REFERENCES actions (id),
                    FOREIGN KEY(risk_id) REFERENCES risk_records (id),
                    FOREIGN KEY(dof_id) REFERENCES dofs (id),
                    FOREIGN KEY(created_by_user_id) REFERENCES users (id)
                )
                """
            )
        )
        changed = True
        tables.add("change_requests")

    if "change_requests" in tables:
        columns = {column["name"] for column in inspector.get_columns("change_requests")}
        change_request_columns = {
            "company_id": "ALTER TABLE change_requests ADD COLUMN company_id INTEGER",
            "change_no": "ALTER TABLE change_requests ADD COLUMN change_no VARCHAR(40) NOT NULL DEFAULT ''",
            "title": "ALTER TABLE change_requests ADD COLUMN title VARCHAR(180) NOT NULL DEFAULT ''",
            "change_type": "ALTER TABLE change_requests ADD COLUMN change_type VARCHAR(60) NOT NULL DEFAULT 'Proses'",
            "description": "ALTER TABLE change_requests ADD COLUMN description TEXT",
            "reason": "ALTER TABLE change_requests ADD COLUMN reason TEXT",
            "scope": "ALTER TABLE change_requests ADD COLUMN scope TEXT",
            "department": "ALTER TABLE change_requests ADD COLUMN department VARCHAR(80)",
            "process_name": "ALTER TABLE change_requests ADD COLUMN process_name VARCHAR(160)",
            "risk_level": "ALTER TABLE change_requests ADD COLUMN risk_level VARCHAR(40) NOT NULL DEFAULT 'Orta'",
            "status": "ALTER TABLE change_requests ADD COLUMN status VARCHAR(40) NOT NULL DEFAULT 'Onay Bekliyor'",
            "planned_date": "ALTER TABLE change_requests ADD COLUMN planned_date DATE",
            "due_date": "ALTER TABLE change_requests ADD COLUMN due_date DATE",
            "effective_date": "ALTER TABLE change_requests ADD COLUMN effective_date DATE",
            "requester_user_id": "ALTER TABLE change_requests ADD COLUMN requester_user_id INTEGER",
            "responsible_user_id": "ALTER TABLE change_requests ADD COLUMN responsible_user_id INTEGER",
            "approver_user_id": "ALTER TABLE change_requests ADD COLUMN approver_user_id INTEGER",
            "document_id": "ALTER TABLE change_requests ADD COLUMN document_id INTEGER",
            "action_id": "ALTER TABLE change_requests ADD COLUMN action_id INTEGER",
            "risk_id": "ALTER TABLE change_requests ADD COLUMN risk_id INTEGER",
            "dof_id": "ALTER TABLE change_requests ADD COLUMN dof_id INTEGER",
            "approval_note": "ALTER TABLE change_requests ADD COLUMN approval_note TEXT",
            "implementation_note": "ALTER TABLE change_requests ADD COLUMN implementation_note TEXT",
            "effectiveness_note": "ALTER TABLE change_requests ADD COLUMN effectiveness_note TEXT",
            "created_by_user_id": "ALTER TABLE change_requests ADD COLUMN created_by_user_id INTEGER",
            "archived_at": "ALTER TABLE change_requests ADD COLUMN archived_at DATETIME",
            "created_at": "ALTER TABLE change_requests ADD COLUMN created_at DATETIME",
            "updated_at": "ALTER TABLE change_requests ADD COLUMN updated_at DATETIME",
        }
        for column_name, statement in change_request_columns.items():
            if column_name not in columns:
                db.session.execute(text(statement))
                changed = True
        for index_name, column_name in (
            ("ix_change_requests_company_id", "company_id"),
            ("ix_change_requests_change_no", "change_no"),
            ("ix_change_requests_status", "status"),
            ("ix_change_requests_due_date", "due_date"),
            ("ix_change_requests_responsible_user_id", "responsible_user_id"),
            ("ix_change_requests_approver_user_id", "approver_user_id"),
        ):
            db.session.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON change_requests ({column_name})"
                )
            )
        db.session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_change_requests_company_change_no "
                "ON change_requests (company_id, change_no)"
            )
        )

    if "change_request_files" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE change_request_files (
                    id INTEGER NOT NULL PRIMARY KEY,
                    company_id INTEGER,
                    change_request_id INTEGER NOT NULL,
                    file_kind VARCHAR(40) NOT NULL DEFAULT 'talep',
                    file_name VARCHAR(255) NOT NULL,
                    original_file_name VARCHAR(255) NOT NULL,
                    file_path VARCHAR(500) NOT NULL,
                    file_type VARCHAR(20),
                    file_size INTEGER,
                    uploaded_by_user_id INTEGER,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(company_id) REFERENCES companies (id),
                    FOREIGN KEY(change_request_id) REFERENCES change_requests (id),
                    FOREIGN KEY(uploaded_by_user_id) REFERENCES users (id)
                )
                """
            )
        )
        changed = True
        tables.add("change_request_files")

    if "change_request_files" in tables:
        columns = {
            column["name"] for column in inspector.get_columns("change_request_files")
        }
        change_file_columns = {
            "company_id": "ALTER TABLE change_request_files ADD COLUMN company_id INTEGER",
            "change_request_id": "ALTER TABLE change_request_files ADD COLUMN change_request_id INTEGER NOT NULL DEFAULT 0",
            "file_kind": "ALTER TABLE change_request_files ADD COLUMN file_kind VARCHAR(40) NOT NULL DEFAULT 'talep'",
            "file_name": "ALTER TABLE change_request_files ADD COLUMN file_name VARCHAR(255) NOT NULL DEFAULT ''",
            "original_file_name": "ALTER TABLE change_request_files ADD COLUMN original_file_name VARCHAR(255) NOT NULL DEFAULT ''",
            "file_path": "ALTER TABLE change_request_files ADD COLUMN file_path VARCHAR(500) NOT NULL DEFAULT ''",
            "file_type": "ALTER TABLE change_request_files ADD COLUMN file_type VARCHAR(20)",
            "file_size": "ALTER TABLE change_request_files ADD COLUMN file_size INTEGER",
            "uploaded_by_user_id": "ALTER TABLE change_request_files ADD COLUMN uploaded_by_user_id INTEGER",
            "created_at": "ALTER TABLE change_request_files ADD COLUMN created_at DATETIME",
        }
        for column_name, statement in change_file_columns.items():
            if column_name not in columns:
                db.session.execute(text(statement))
                changed = True
        for index_name, column_name in (
            ("ix_change_request_files_company_id", "company_id"),
            ("ix_change_request_files_change_request_id", "change_request_id"),
            ("ix_change_request_files_uploaded_by_user_id", "uploaded_by_user_id"),
        ):
            db.session.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON change_request_files ({column_name})"
                )
            )

    if "deviation_records" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE deviation_records (
                    id INTEGER NOT NULL PRIMARY KEY,
                    company_id INTEGER,
                    deviation_no VARCHAR(40) NOT NULL,
                    record_type VARCHAR(80) NOT NULL DEFAULT 'Uygunsuz Ürün',
                    source_type VARCHAR(80),
                    title VARCHAR(180) NOT NULL,
                    description TEXT,
                    detected_date DATE NOT NULL,
                    department VARCHAR(80),
                    process_name VARCHAR(160),
                    product_name VARCHAR(180),
                    batch_no VARCHAR(120),
                    quantity VARCHAR(80),
                    severity VARCHAR(40) NOT NULL DEFAULT 'Orta',
                    containment_action TEXT,
                    quarantine_location VARCHAR(180),
                    disposition VARCHAR(80),
                    disposition_note TEXT,
                    root_cause TEXT,
                    corrective_action TEXT,
                    due_date DATE,
                    closed_at DATE,
                    status VARCHAR(40) NOT NULL DEFAULT 'Açık',
                    responsible_user_id INTEGER,
                    approver_user_id INTEGER,
                    document_id INTEGER,
                    action_id INTEGER,
                    risk_id INTEGER,
                    dof_id INTEGER,
                    created_by_user_id INTEGER,
                    archived_at DATETIME,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(company_id) REFERENCES companies (id),
                    FOREIGN KEY(responsible_user_id) REFERENCES users (id),
                    FOREIGN KEY(approver_user_id) REFERENCES users (id),
                    FOREIGN KEY(document_id) REFERENCES documents (id),
                    FOREIGN KEY(action_id) REFERENCES actions (id),
                    FOREIGN KEY(risk_id) REFERENCES risk_records (id),
                    FOREIGN KEY(dof_id) REFERENCES dofs (id),
                    FOREIGN KEY(created_by_user_id) REFERENCES users (id)
                )
                """
            )
        )
        changed = True
        tables.add("deviation_records")

    if "deviation_records" in tables:
        columns = {column["name"] for column in inspector.get_columns("deviation_records")}
        deviation_record_columns = {
            "company_id": "ALTER TABLE deviation_records ADD COLUMN company_id INTEGER",
            "deviation_no": "ALTER TABLE deviation_records ADD COLUMN deviation_no VARCHAR(40) NOT NULL DEFAULT ''",
            "record_type": "ALTER TABLE deviation_records ADD COLUMN record_type VARCHAR(80) NOT NULL DEFAULT 'Uygunsuz Ürün'",
            "source_type": "ALTER TABLE deviation_records ADD COLUMN source_type VARCHAR(80)",
            "title": "ALTER TABLE deviation_records ADD COLUMN title VARCHAR(180) NOT NULL DEFAULT ''",
            "description": "ALTER TABLE deviation_records ADD COLUMN description TEXT",
            "detected_date": "ALTER TABLE deviation_records ADD COLUMN detected_date DATE",
            "department": "ALTER TABLE deviation_records ADD COLUMN department VARCHAR(80)",
            "process_name": "ALTER TABLE deviation_records ADD COLUMN process_name VARCHAR(160)",
            "product_name": "ALTER TABLE deviation_records ADD COLUMN product_name VARCHAR(180)",
            "batch_no": "ALTER TABLE deviation_records ADD COLUMN batch_no VARCHAR(120)",
            "quantity": "ALTER TABLE deviation_records ADD COLUMN quantity VARCHAR(80)",
            "severity": "ALTER TABLE deviation_records ADD COLUMN severity VARCHAR(40) NOT NULL DEFAULT 'Orta'",
            "containment_action": "ALTER TABLE deviation_records ADD COLUMN containment_action TEXT",
            "quarantine_location": "ALTER TABLE deviation_records ADD COLUMN quarantine_location VARCHAR(180)",
            "disposition": "ALTER TABLE deviation_records ADD COLUMN disposition VARCHAR(80)",
            "disposition_note": "ALTER TABLE deviation_records ADD COLUMN disposition_note TEXT",
            "root_cause": "ALTER TABLE deviation_records ADD COLUMN root_cause TEXT",
            "corrective_action": "ALTER TABLE deviation_records ADD COLUMN corrective_action TEXT",
            "due_date": "ALTER TABLE deviation_records ADD COLUMN due_date DATE",
            "closed_at": "ALTER TABLE deviation_records ADD COLUMN closed_at DATE",
            "status": "ALTER TABLE deviation_records ADD COLUMN status VARCHAR(40) NOT NULL DEFAULT 'Açık'",
            "responsible_user_id": "ALTER TABLE deviation_records ADD COLUMN responsible_user_id INTEGER",
            "approver_user_id": "ALTER TABLE deviation_records ADD COLUMN approver_user_id INTEGER",
            "document_id": "ALTER TABLE deviation_records ADD COLUMN document_id INTEGER",
            "action_id": "ALTER TABLE deviation_records ADD COLUMN action_id INTEGER",
            "risk_id": "ALTER TABLE deviation_records ADD COLUMN risk_id INTEGER",
            "dof_id": "ALTER TABLE deviation_records ADD COLUMN dof_id INTEGER",
            "created_by_user_id": "ALTER TABLE deviation_records ADD COLUMN created_by_user_id INTEGER",
            "archived_at": "ALTER TABLE deviation_records ADD COLUMN archived_at DATETIME",
            "created_at": "ALTER TABLE deviation_records ADD COLUMN created_at DATETIME",
            "updated_at": "ALTER TABLE deviation_records ADD COLUMN updated_at DATETIME",
        }
        for column_name, statement in deviation_record_columns.items():
            if column_name not in columns:
                db.session.execute(text(statement))
                changed = True
        for index_name, column_name in (
            ("ix_deviation_records_company_id", "company_id"),
            ("ix_deviation_records_deviation_no", "deviation_no"),
            ("ix_deviation_records_status", "status"),
            ("ix_deviation_records_due_date", "due_date"),
            ("ix_deviation_records_responsible_user_id", "responsible_user_id"),
            ("ix_deviation_records_approver_user_id", "approver_user_id"),
        ):
            db.session.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON deviation_records ({column_name})"
                )
            )
        db.session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_deviation_records_company_deviation_no "
                "ON deviation_records (company_id, deviation_no)"
            )
        )

    if "deviation_files" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE deviation_files (
                    id INTEGER NOT NULL PRIMARY KEY,
                    company_id INTEGER,
                    deviation_id INTEGER NOT NULL,
                    file_kind VARCHAR(40) NOT NULL DEFAULT 'tespit',
                    file_name VARCHAR(255) NOT NULL,
                    original_file_name VARCHAR(255) NOT NULL,
                    file_path VARCHAR(500) NOT NULL,
                    file_type VARCHAR(20),
                    file_size INTEGER,
                    uploaded_by_user_id INTEGER,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(company_id) REFERENCES companies (id),
                    FOREIGN KEY(deviation_id) REFERENCES deviation_records (id),
                    FOREIGN KEY(uploaded_by_user_id) REFERENCES users (id)
                )
                """
            )
        )
        changed = True
        tables.add("deviation_files")

    if "deviation_files" in tables:
        columns = {column["name"] for column in inspector.get_columns("deviation_files")}
        deviation_file_columns = {
            "company_id": "ALTER TABLE deviation_files ADD COLUMN company_id INTEGER",
            "deviation_id": "ALTER TABLE deviation_files ADD COLUMN deviation_id INTEGER NOT NULL DEFAULT 0",
            "file_kind": "ALTER TABLE deviation_files ADD COLUMN file_kind VARCHAR(40) NOT NULL DEFAULT 'tespit'",
            "file_name": "ALTER TABLE deviation_files ADD COLUMN file_name VARCHAR(255) NOT NULL DEFAULT ''",
            "original_file_name": "ALTER TABLE deviation_files ADD COLUMN original_file_name VARCHAR(255) NOT NULL DEFAULT ''",
            "file_path": "ALTER TABLE deviation_files ADD COLUMN file_path VARCHAR(500) NOT NULL DEFAULT ''",
            "file_type": "ALTER TABLE deviation_files ADD COLUMN file_type VARCHAR(20)",
            "file_size": "ALTER TABLE deviation_files ADD COLUMN file_size INTEGER",
            "uploaded_by_user_id": "ALTER TABLE deviation_files ADD COLUMN uploaded_by_user_id INTEGER",
            "created_at": "ALTER TABLE deviation_files ADD COLUMN created_at DATETIME",
        }
        for column_name, statement in deviation_file_columns.items():
            if column_name not in columns:
                db.session.execute(text(statement))
                changed = True
        for index_name, column_name in (
            ("ix_deviation_files_company_id", "company_id"),
            ("ix_deviation_files_deviation_id", "deviation_id"),
            ("ix_deviation_files_uploaded_by_user_id", "uploaded_by_user_id"),
        ):
            db.session.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON deviation_files ({column_name})"
                )
            )

    if "incident_reports" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE incident_reports (
                    id INTEGER NOT NULL PRIMARY KEY,
                    company_id INTEGER,
                    incident_no VARCHAR(40) NOT NULL,
                    report_type VARCHAR(80) NOT NULL DEFAULT 'Ramak Kala',
                    title VARCHAR(180) NOT NULL,
                    description TEXT,
                    incident_date DATE NOT NULL,
                    incident_time VARCHAR(20),
                    department VARCHAR(80),
                    location VARCHAR(180),
                    process_name VARCHAR(160),
                    affected_person VARCHAR(180),
                    witness VARCHAR(180),
                    severity VARCHAR(40) NOT NULL DEFAULT 'Orta',
                    probability INTEGER,
                    risk_score INTEGER,
                    immediate_action TEXT,
                    root_cause TEXT,
                    decision VARCHAR(100),
                    decision_note TEXT,
                    corrective_action TEXT,
                    due_date DATE,
                    closed_at DATE,
                    status VARCHAR(40) NOT NULL DEFAULT 'Yeni Bildirim',
                    reported_by_user_id INTEGER,
                    reviewer_user_id INTEGER,
                    responsible_user_id INTEGER,
                    document_id INTEGER,
                    action_id INTEGER,
                    risk_id INTEGER,
                    dof_id INTEGER,
                    deviation_id INTEGER,
                    archived_at DATETIME,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(company_id) REFERENCES companies (id),
                    FOREIGN KEY(reported_by_user_id) REFERENCES users (id),
                    FOREIGN KEY(reviewer_user_id) REFERENCES users (id),
                    FOREIGN KEY(responsible_user_id) REFERENCES users (id),
                    FOREIGN KEY(document_id) REFERENCES documents (id),
                    FOREIGN KEY(action_id) REFERENCES actions (id),
                    FOREIGN KEY(risk_id) REFERENCES risk_records (id),
                    FOREIGN KEY(dof_id) REFERENCES dofs (id),
                    FOREIGN KEY(deviation_id) REFERENCES deviation_records (id)
                )
                """
            )
        )
        changed = True
        tables.add("incident_reports")

    if "incident_reports" in tables:
        columns = {column["name"] for column in inspector.get_columns("incident_reports")}
        incident_report_columns = {
            "company_id": "ALTER TABLE incident_reports ADD COLUMN company_id INTEGER",
            "incident_no": "ALTER TABLE incident_reports ADD COLUMN incident_no VARCHAR(40) NOT NULL DEFAULT ''",
            "report_type": "ALTER TABLE incident_reports ADD COLUMN report_type VARCHAR(80) NOT NULL DEFAULT 'Ramak Kala'",
            "title": "ALTER TABLE incident_reports ADD COLUMN title VARCHAR(180) NOT NULL DEFAULT ''",
            "description": "ALTER TABLE incident_reports ADD COLUMN description TEXT",
            "incident_date": "ALTER TABLE incident_reports ADD COLUMN incident_date DATE",
            "incident_time": "ALTER TABLE incident_reports ADD COLUMN incident_time VARCHAR(20)",
            "department": "ALTER TABLE incident_reports ADD COLUMN department VARCHAR(80)",
            "location": "ALTER TABLE incident_reports ADD COLUMN location VARCHAR(180)",
            "process_name": "ALTER TABLE incident_reports ADD COLUMN process_name VARCHAR(160)",
            "affected_person": "ALTER TABLE incident_reports ADD COLUMN affected_person VARCHAR(180)",
            "witness": "ALTER TABLE incident_reports ADD COLUMN witness VARCHAR(180)",
            "severity": "ALTER TABLE incident_reports ADD COLUMN severity VARCHAR(40) NOT NULL DEFAULT 'Orta'",
            "probability": "ALTER TABLE incident_reports ADD COLUMN probability INTEGER",
            "risk_score": "ALTER TABLE incident_reports ADD COLUMN risk_score INTEGER",
            "immediate_action": "ALTER TABLE incident_reports ADD COLUMN immediate_action TEXT",
            "root_cause": "ALTER TABLE incident_reports ADD COLUMN root_cause TEXT",
            "decision": "ALTER TABLE incident_reports ADD COLUMN decision VARCHAR(100)",
            "decision_note": "ALTER TABLE incident_reports ADD COLUMN decision_note TEXT",
            "corrective_action": "ALTER TABLE incident_reports ADD COLUMN corrective_action TEXT",
            "due_date": "ALTER TABLE incident_reports ADD COLUMN due_date DATE",
            "closed_at": "ALTER TABLE incident_reports ADD COLUMN closed_at DATE",
            "status": "ALTER TABLE incident_reports ADD COLUMN status VARCHAR(40) NOT NULL DEFAULT 'Yeni Bildirim'",
            "reported_by_user_id": "ALTER TABLE incident_reports ADD COLUMN reported_by_user_id INTEGER",
            "reviewer_user_id": "ALTER TABLE incident_reports ADD COLUMN reviewer_user_id INTEGER",
            "responsible_user_id": "ALTER TABLE incident_reports ADD COLUMN responsible_user_id INTEGER",
            "document_id": "ALTER TABLE incident_reports ADD COLUMN document_id INTEGER",
            "action_id": "ALTER TABLE incident_reports ADD COLUMN action_id INTEGER",
            "risk_id": "ALTER TABLE incident_reports ADD COLUMN risk_id INTEGER",
            "dof_id": "ALTER TABLE incident_reports ADD COLUMN dof_id INTEGER",
            "deviation_id": "ALTER TABLE incident_reports ADD COLUMN deviation_id INTEGER",
            "archived_at": "ALTER TABLE incident_reports ADD COLUMN archived_at DATETIME",
            "created_at": "ALTER TABLE incident_reports ADD COLUMN created_at DATETIME",
            "updated_at": "ALTER TABLE incident_reports ADD COLUMN updated_at DATETIME",
        }
        for column_name, statement in incident_report_columns.items():
            if column_name not in columns:
                db.session.execute(text(statement))
                changed = True
        for index_name, column_name in (
            ("ix_incident_reports_company_id", "company_id"),
            ("ix_incident_reports_incident_no", "incident_no"),
            ("ix_incident_reports_status", "status"),
            ("ix_incident_reports_due_date", "due_date"),
            ("ix_incident_reports_reviewer_user_id", "reviewer_user_id"),
            ("ix_incident_reports_responsible_user_id", "responsible_user_id"),
            ("ix_incident_reports_reported_by_user_id", "reported_by_user_id"),
        ):
            db.session.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON incident_reports ({column_name})"
                )
            )
        db.session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_incident_reports_company_incident_no "
                "ON incident_reports (company_id, incident_no)"
            )
        )

    if "incident_files" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE incident_files (
                    id INTEGER NOT NULL PRIMARY KEY,
                    company_id INTEGER,
                    incident_id INTEGER NOT NULL,
                    file_kind VARCHAR(40) NOT NULL DEFAULT 'bildirim',
                    file_name VARCHAR(255) NOT NULL,
                    original_file_name VARCHAR(255) NOT NULL,
                    file_path VARCHAR(500) NOT NULL,
                    file_type VARCHAR(20),
                    file_size INTEGER,
                    uploaded_by_user_id INTEGER,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(company_id) REFERENCES companies (id),
                    FOREIGN KEY(incident_id) REFERENCES incident_reports (id),
                    FOREIGN KEY(uploaded_by_user_id) REFERENCES users (id)
                )
                """
            )
        )
        changed = True
        tables.add("incident_files")

    if "incident_files" in tables:
        columns = {column["name"] for column in inspector.get_columns("incident_files")}
        incident_file_columns = {
            "company_id": "ALTER TABLE incident_files ADD COLUMN company_id INTEGER",
            "incident_id": "ALTER TABLE incident_files ADD COLUMN incident_id INTEGER NOT NULL DEFAULT 0",
            "file_kind": "ALTER TABLE incident_files ADD COLUMN file_kind VARCHAR(40) NOT NULL DEFAULT 'bildirim'",
            "file_name": "ALTER TABLE incident_files ADD COLUMN file_name VARCHAR(255) NOT NULL DEFAULT ''",
            "original_file_name": "ALTER TABLE incident_files ADD COLUMN original_file_name VARCHAR(255) NOT NULL DEFAULT ''",
            "file_path": "ALTER TABLE incident_files ADD COLUMN file_path VARCHAR(500) NOT NULL DEFAULT ''",
            "file_type": "ALTER TABLE incident_files ADD COLUMN file_type VARCHAR(20)",
            "file_size": "ALTER TABLE incident_files ADD COLUMN file_size INTEGER",
            "uploaded_by_user_id": "ALTER TABLE incident_files ADD COLUMN uploaded_by_user_id INTEGER",
            "created_at": "ALTER TABLE incident_files ADD COLUMN created_at DATETIME",
        }
        for column_name, statement in incident_file_columns.items():
            if column_name not in columns:
                db.session.execute(text(statement))
                changed = True
        for index_name, column_name in (
            ("ix_incident_files_company_id", "company_id"),
            ("ix_incident_files_incident_id", "incident_id"),
            ("ix_incident_files_uploaded_by_user_id", "uploaded_by_user_id"),
        ):
            db.session.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON incident_files ({column_name})"
                )
            )

    if "training_records" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE training_records (
                    id INTEGER NOT NULL PRIMARY KEY,
                    company_id INTEGER,
                    training_no VARCHAR(30) NOT NULL,
                    title VARCHAR(180) NOT NULL,
                    training_type VARCHAR(60) NOT NULL DEFAULT 'Eğitim',
                    description TEXT,
                    document_id INTEGER,
                    document_revision_no_snapshot VARCHAR(40),
                    planned_date DATE,
                    due_date DATE,
                    instructor_user_id INTEGER,
                    status VARCHAR(40) NOT NULL DEFAULT 'Planlandı',
                    created_by_user_id INTEGER,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(company_id) REFERENCES companies (id),
                    FOREIGN KEY(document_id) REFERENCES documents (id),
                    FOREIGN KEY(instructor_user_id) REFERENCES users (id),
                    FOREIGN KEY(created_by_user_id) REFERENCES users (id)
                )
                """
            )
        )
        changed = True
        tables.add("training_records")

    if "training_records" in tables:
        columns = {column["name"] for column in inspector.get_columns("training_records")}
        if "document_revision_no_snapshot" not in columns:
            db.session.execute(
                text(
                    "ALTER TABLE training_records "
                    "ADD COLUMN document_revision_no_snapshot VARCHAR(40)"
                )
            )
            changed = True
            columns.add("document_revision_no_snapshot")
        if "documents" in tables and "document_revision_no_snapshot" in columns:
            result = db.session.execute(
                text(
                    """
                    UPDATE training_records
                    SET document_revision_no_snapshot = COALESCE(
                        (
                            SELECT documents.revision_no
                            FROM documents
                            WHERE documents.id = training_records.document_id
                        ),
                        ''
                    )
                    WHERE document_revision_no_snapshot IS NULL
                      AND training_type = 'Doküman Okuma Onayı'
                      AND document_id IS NOT NULL
                    """
                )
            )
            if result.rowcount:
                changed = True
        for index_name, column_name in (
            ("ix_training_records_company_id", "company_id"),
            ("ix_training_records_document_id", "document_id"),
            ("ix_training_records_instructor_user_id", "instructor_user_id"),
        ):
            db.session.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON training_records ({column_name})"
                )
            )
        db.session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_training_records_company_training_no "
                "ON training_records (company_id, training_no)"
            )
        )

    if "training_participants" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE training_participants (
                    id INTEGER NOT NULL PRIMARY KEY,
                    company_id INTEGER,
                    training_id INTEGER NOT NULL,
                    user_id INTEGER,
                    personnel_contact_id INTEGER,
                    status VARCHAR(40) NOT NULL DEFAULT 'Atandı',
                    read_confirmed_at DATETIME,
                    attended_at DATETIME,
                    score NUMERIC(5, 2),
                    notes TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(company_id) REFERENCES companies (id),
                    FOREIGN KEY(training_id) REFERENCES training_records (id),
                    FOREIGN KEY(user_id) REFERENCES users (id),
                    FOREIGN KEY(personnel_contact_id) REFERENCES personnel_contacts (id)
                )
                """
            )
        )
        changed = True
        tables.add("training_participants")

    if "training_participants" in tables:
        for index_name, column_name in (
            ("ix_training_participants_company_id", "company_id"),
            ("ix_training_participants_training_id", "training_id"),
            ("ix_training_participants_user_id", "user_id"),
            ("ix_training_participants_personnel_contact_id", "personnel_contact_id"),
        ):
            db.session.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON training_participants ({column_name})"
                )
            )

    if "complaint_records" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE complaint_records (
                    id INTEGER NOT NULL PRIMARY KEY,
                    company_id INTEGER,
                    complaint_no VARCHAR(30) NOT NULL,
                    customer_name VARCHAR(180) NOT NULL,
                    contact_name VARCHAR(160),
                    contact_phone VARCHAR(80),
                    department VARCHAR(80),
                    subject VARCHAR(180) NOT NULL,
                    description TEXT,
                    root_cause TEXT,
                    corrective_action TEXT,
                    closing_note TEXT,
                    received_date DATE,
                    due_date DATE,
                    closed_at DATETIME,
                    status VARCHAR(40) NOT NULL DEFAULT 'Açık',
                    priority VARCHAR(40) NOT NULL DEFAULT 'Orta',
                    responsible_user_id INTEGER,
                    action_id INTEGER,
                    dof_id INTEGER,
                    created_by_user_id INTEGER,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(company_id) REFERENCES companies (id),
                    FOREIGN KEY(responsible_user_id) REFERENCES users (id),
                    FOREIGN KEY(action_id) REFERENCES actions (id),
                    FOREIGN KEY(dof_id) REFERENCES dofs (id),
                    FOREIGN KEY(created_by_user_id) REFERENCES users (id)
                )
                """
            )
        )
        changed = True
        tables.add("complaint_records")

    if "complaint_records" in tables:
        for index_name, column_name in (
            ("ix_complaint_records_company_id", "company_id"),
            ("ix_complaint_records_responsible_user_id", "responsible_user_id"),
            ("ix_complaint_records_action_id", "action_id"),
            ("ix_complaint_records_dof_id", "dof_id"),
            ("ix_complaint_records_status", "status"),
            ("ix_complaint_records_due_date", "due_date"),
        ):
            db.session.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON complaint_records ({column_name})"
                )
            )
        db.session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_complaint_records_company_complaint_no "
                "ON complaint_records (company_id, complaint_no)"
            )
        )

    if "management_reviews" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE management_reviews (
                    id INTEGER NOT NULL PRIMARY KEY,
                    company_id INTEGER,
                    review_no VARCHAR(30) NOT NULL,
                    title VARCHAR(180) NOT NULL,
                    review_period VARCHAR(80),
                    meeting_date DATE,
                    location VARCHAR(160),
                    status VARCHAR(40) NOT NULL DEFAULT 'Planlandı',
                    chair_user_id INTEGER,
                    recorder_user_id INTEGER,
                    participants TEXT,
                    agenda TEXT,
                    audit_results TEXT,
                    customer_feedback TEXT,
                    process_performance TEXT,
                    nonconformities TEXT,
                    corrective_actions TEXT,
                    monitoring_results TEXT,
                    supplier_performance TEXT,
                    resource_needs TEXT,
                    risk_opportunities TEXT,
                    decisions TEXT,
                    outputs TEXT,
                    improvement_opportunities TEXT,
                    action_id INTEGER,
                    created_by_user_id INTEGER,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(company_id) REFERENCES companies (id),
                    FOREIGN KEY(chair_user_id) REFERENCES users (id),
                    FOREIGN KEY(recorder_user_id) REFERENCES users (id),
                    FOREIGN KEY(action_id) REFERENCES actions (id),
                    FOREIGN KEY(created_by_user_id) REFERENCES users (id)
                )
                """
            )
        )
        changed = True
        tables.add("management_reviews")

    if "management_reviews" in tables:
        for index_name, column_name in (
            ("ix_management_reviews_company_id", "company_id"),
            ("ix_management_reviews_chair_user_id", "chair_user_id"),
            ("ix_management_reviews_recorder_user_id", "recorder_user_id"),
            ("ix_management_reviews_action_id", "action_id"),
            ("ix_management_reviews_status", "status"),
            ("ix_management_reviews_meeting_date", "meeting_date"),
        ):
            db.session.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON management_reviews ({column_name})"
                )
            )
        db.session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_management_reviews_company_review_no "
                "ON management_reviews (company_id, review_no)"
            )
        )

    if "supplier_records" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE supplier_records (
                    id INTEGER NOT NULL PRIMARY KEY,
                    company_id INTEGER,
                    supplier_no VARCHAR(30) NOT NULL,
                    name VARCHAR(180) NOT NULL,
                    product_group VARCHAR(160),
                    department VARCHAR(80),
                    contact_person VARCHAR(160),
                    phone VARCHAR(80),
                    email VARCHAR(160),
                    status VARCHAR(40) NOT NULL DEFAULT 'Değerlendirme Bekliyor',
                    last_score INTEGER,
                    last_evaluation_date DATE,
                    next_evaluation_date DATE,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    created_by_user_id INTEGER,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(company_id) REFERENCES companies (id),
                    FOREIGN KEY(created_by_user_id) REFERENCES users (id)
                )
                """
            )
        )
        changed = True
        tables.add("supplier_records")

    if "supplier_records" in tables:
        for index_name, column_name in (
            ("ix_supplier_records_company_id", "company_id"),
            ("ix_supplier_records_status", "status"),
            ("ix_supplier_records_next_evaluation_date", "next_evaluation_date"),
            ("ix_supplier_records_created_by_user_id", "created_by_user_id"),
        ):
            db.session.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON supplier_records ({column_name})"
                )
            )
        db.session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_supplier_records_company_supplier_no "
                "ON supplier_records (company_id, supplier_no)"
            )
        )

    if "supplier_evaluations" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE supplier_evaluations (
                    id INTEGER NOT NULL PRIMARY KEY,
                    company_id INTEGER,
                    supplier_id INTEGER NOT NULL,
                    evaluation_date DATE NOT NULL,
                    evaluated_by_user_id INTEGER,
                    quality_score INTEGER NOT NULL,
                    delivery_score INTEGER NOT NULL,
                    cost_score INTEGER NOT NULL,
                    communication_score INTEGER NOT NULL,
                    documentation_score INTEGER NOT NULL,
                    nonconformity_score INTEGER NOT NULL,
                    total_score INTEGER NOT NULL,
                    result_status VARCHAR(40) NOT NULL,
                    next_evaluation_date DATE,
                    notes TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(company_id) REFERENCES companies (id),
                    FOREIGN KEY(supplier_id) REFERENCES supplier_records (id),
                    FOREIGN KEY(evaluated_by_user_id) REFERENCES users (id)
                )
                """
            )
        )
        changed = True
        tables.add("supplier_evaluations")

    if "supplier_evaluations" in tables:
        for index_name, column_name in (
            ("ix_supplier_evaluations_company_id", "company_id"),
            ("ix_supplier_evaluations_supplier_id", "supplier_id"),
            ("ix_supplier_evaluations_evaluated_by_user_id", "evaluated_by_user_id"),
            ("ix_supplier_evaluations_evaluation_date", "evaluation_date"),
        ):
            db.session.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON supplier_evaluations ({column_name})"
                )
            )

    if "roles" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE roles (
                    id INTEGER NOT NULL PRIMARY KEY,
                    key VARCHAR(80) NOT NULL UNIQUE,
                    name VARCHAR(160) NOT NULL,
                    description TEXT,
                    hierarchy_level INTEGER NOT NULL DEFAULT 100,
                    is_system BOOLEAN NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        changed = True

    if "role_permissions" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE role_permissions (
                    role_id INTEGER NOT NULL,
                    permission_key VARCHAR(120) NOT NULL,
                    PRIMARY KEY (role_id, permission_key),
                    FOREIGN KEY(role_id) REFERENCES roles (id)
                )
                """
            )
        )
        changed = True

    if "user_roles" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE user_roles (
                    user_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    PRIMARY KEY (user_id, role_id),
                    FOREIGN KEY(user_id) REFERENCES users (id),
                    FOREIGN KEY(role_id) REFERENCES roles (id)
                )
                """
            )
        )
        changed = True

    if "user_permissions" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE user_permissions (
                    user_id INTEGER NOT NULL,
                    permission_key VARCHAR(120) NOT NULL,
                    PRIMARY KEY (user_id, permission_key),
                    FOREIGN KEY(user_id) REFERENCES users (id)
                )
                """
            )
        )
        changed = True

    if "actions" in tables:
        columns = {column["name"] for column in inspector.get_columns("actions")}
        if "action_number" not in columns:
            db.session.execute(text("ALTER TABLE actions ADD COLUMN action_number INTEGER"))
            changed = True
        if "related_user_1_id" not in columns:
            db.session.execute(
                text("ALTER TABLE actions ADD COLUMN related_user_1_id INTEGER")
            )
            changed = True
        if "related_user_2_id" not in columns:
            db.session.execute(
                text("ALTER TABLE actions ADD COLUMN related_user_2_id INTEGER")
            )
            changed = True
        if "closure_approval_requested" not in columns:
            db.session.execute(
                text(
                    "ALTER TABLE actions ADD COLUMN "
                    "closure_approval_requested BOOLEAN NOT NULL DEFAULT 0"
                )
            )
            changed = True
        if "closure_requested_at" not in columns:
            db.session.execute(text("ALTER TABLE actions ADD COLUMN closure_requested_at DATETIME"))
            changed = True
        if "closure_requested_by_user_id" not in columns:
            db.session.execute(
                text("ALTER TABLE actions ADD COLUMN closure_requested_by_user_id INTEGER")
            )
            changed = True
        if "closure_evidence_note" not in columns:
            db.session.execute(text("ALTER TABLE actions ADD COLUMN closure_evidence_note TEXT"))
            changed = True
        if "closure_file_original_name" not in columns:
            db.session.execute(
                text("ALTER TABLE actions ADD COLUMN closure_file_original_name VARCHAR(255)")
            )
            changed = True
        if "closure_file_stored_name" not in columns:
            db.session.execute(
                text("ALTER TABLE actions ADD COLUMN closure_file_stored_name VARCHAR(255)")
            )
            changed = True
        if "closure_file_mime_type" not in columns:
            db.session.execute(
                text("ALTER TABLE actions ADD COLUMN closure_file_mime_type VARCHAR(120)")
            )
            changed = True
        if "closure_rejected_at" not in columns:
            db.session.execute(text("ALTER TABLE actions ADD COLUMN closure_rejected_at DATETIME"))
            changed = True
        if "closure_rejected_by_user_id" not in columns:
            db.session.execute(
                text("ALTER TABLE actions ADD COLUMN closure_rejected_by_user_id INTEGER")
            )
            changed = True
        if "closure_rejection_reason" not in columns:
            db.session.execute(text("ALTER TABLE actions ADD COLUMN closure_rejection_reason TEXT"))
            changed = True
        action_capa_columns = {
            "dof_id": "ALTER TABLE actions ADD COLUMN dof_id INTEGER",
            "capa_type": "ALTER TABLE actions ADD COLUMN capa_type VARCHAR(60)",
            "effectiveness_required": (
                "ALTER TABLE actions ADD COLUMN "
                "effectiveness_required BOOLEAN NOT NULL DEFAULT 0"
            ),
            "effectiveness_owner_user_id": (
                "ALTER TABLE actions ADD COLUMN effectiveness_owner_user_id INTEGER"
            ),
            "effectiveness_due_date": (
                "ALTER TABLE actions ADD COLUMN effectiveness_due_date DATE"
            ),
            "effectiveness_result": (
                "ALTER TABLE actions ADD COLUMN effectiveness_result VARCHAR(40)"
            ),
            "effectiveness_note": "ALTER TABLE actions ADD COLUMN effectiveness_note TEXT",
            "effectiveness_checked_by_user_id": (
                "ALTER TABLE actions ADD COLUMN effectiveness_checked_by_user_id INTEGER"
            ),
            "effectiveness_checked_at": (
                "ALTER TABLE actions ADD COLUMN effectiveness_checked_at DATETIME"
            ),
        }
        for column_name, statement in action_capa_columns.items():
            if column_name not in columns:
                db.session.execute(text(statement))
                changed = True
        db.session.execute(text("CREATE INDEX IF NOT EXISTS ix_actions_dof_id ON actions (dof_id)"))
        db.session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_actions_effectiveness_owner_user_id "
                "ON actions (effectiveness_owner_user_id)"
            )
        )

    if "action_closure_files" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE action_closure_files (
                    id INTEGER NOT NULL PRIMARY KEY,
                    action_id INTEGER NOT NULL,
                    original_name VARCHAR(255) NOT NULL,
                    stored_name VARCHAR(255) NOT NULL,
                    mime_type VARCHAR(120),
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(action_id) REFERENCES actions (id)
                )
                """
            )
        )
        changed = True

    if "action_sub_tasks" not in tables:
        db.session.execute(
            text(
                """
                CREATE TABLE action_sub_tasks (
                    id INTEGER NOT NULL PRIMARY KEY,
                    parent_action_id INTEGER NOT NULL,
                    title VARCHAR(160) NOT NULL,
                    description TEXT,
                    responsible_id INTEGER,
                    related_user_1_id INTEGER,
                    related_user_2_id INTEGER,
                    due_date DATE,
                    priority VARCHAR(40) NOT NULL DEFAULT 'Orta',
                    status VARCHAR(40) NOT NULL DEFAULT 'Beklemede',
                    evidence_required BOOLEAN NOT NULL DEFAULT 0,
                    evidence_original_name VARCHAR(255),
                    evidence_stored_name VARCHAR(255),
                    evidence_mime_type VARCHAR(120),
                    closing_note TEXT,
                    completed_at DATETIME,
                    completed_by_user_id INTEGER,
                    created_by_user_id INTEGER,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(parent_action_id) REFERENCES actions (id),
                    FOREIGN KEY(responsible_id) REFERENCES users (id),
                    FOREIGN KEY(related_user_1_id) REFERENCES users (id),
                    FOREIGN KEY(related_user_2_id) REFERENCES users (id),
                    FOREIGN KEY(completed_by_user_id) REFERENCES users (id),
                    FOREIGN KEY(created_by_user_id) REFERENCES users (id)
                )
                """
            )
        )
        changed = True
    else:
        columns = {
            column["name"] for column in inspector.get_columns("action_sub_tasks")
        }
        action_sub_task_columns = {
            "related_user_1_id": (
                "ALTER TABLE action_sub_tasks "
                "ADD COLUMN related_user_1_id INTEGER"
            ),
            "related_user_2_id": (
                "ALTER TABLE action_sub_tasks "
                "ADD COLUMN related_user_2_id INTEGER"
            ),
        }
        for column_name, statement in action_sub_task_columns.items():
            if column_name not in columns:
                db.session.execute(text(statement))
                changed = True

    if "orientation_nodes" in tables:
        columns = {
            column["name"] for column in inspector.get_columns("orientation_nodes")
        }
        if "node_type" not in columns:
            db.session.execute(
                text(
                    "ALTER TABLE orientation_nodes "
                    "ADD COLUMN node_type VARCHAR(40) NOT NULL DEFAULT 'person'"
                )
            )
            changed = True
        if "color" not in columns:
            db.session.execute(
                text(
                    "ALTER TABLE orientation_nodes "
                    "ADD COLUMN color VARCHAR(20) NOT NULL DEFAULT '#198754'"
                )
            )
            changed = True
        if "personnel_contact_id" not in columns:
            db.session.execute(
                text(
                    "ALTER TABLE orientation_nodes "
                    "ADD COLUMN personnel_contact_id INTEGER"
                )
            )
            changed = True
        db.session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_orientation_nodes_personnel_contact_id "
                "ON orientation_nodes (personnel_contact_id)"
            )
        )

    if "dofs" in tables:
        columns = {column["name"] for column in inspector.get_columns("dofs")}
        if "approval_step" not in columns:
            db.session.execute(
                text(
                    "ALTER TABLE dofs "
                    "ADD COLUMN approval_step VARCHAR(40) NOT NULL DEFAULT 'draft'"
                )
            )
            changed = True
        if "management_approved_by_user_id" not in columns:
            db.session.execute(
                text("ALTER TABLE dofs ADD COLUMN management_approved_by_user_id INTEGER")
            )
            changed = True
        if "management_approved_at" not in columns:
            db.session.execute(text("ALTER TABLE dofs ADD COLUMN management_approved_at DATETIME"))
            changed = True
        if "deputy_approved_by_user_id" not in columns:
            db.session.execute(
                text("ALTER TABLE dofs ADD COLUMN deputy_approved_by_user_id INTEGER")
            )
            changed = True
        if "deputy_approved_at" not in columns:
            db.session.execute(text("ALTER TABLE dofs ADD COLUMN deputy_approved_at DATETIME"))
            changed = True
        if "completed_at" not in columns:
            db.session.execute(text("ALTER TABLE dofs ADD COLUMN completed_at DATETIME"))
            changed = True
        dof_capa_columns = {
            "containment_action": "ALTER TABLE dofs ADD COLUMN containment_action TEXT",
            "root_cause_method": "ALTER TABLE dofs ADD COLUMN root_cause_method VARCHAR(80)",
            "effectiveness_required": (
                "ALTER TABLE dofs ADD COLUMN "
                "effectiveness_required BOOLEAN NOT NULL DEFAULT 0"
            ),
            "effectiveness_owner_user_id": (
                "ALTER TABLE dofs ADD COLUMN effectiveness_owner_user_id INTEGER"
            ),
            "effectiveness_due_date": (
                "ALTER TABLE dofs ADD COLUMN effectiveness_due_date DATE"
            ),
            "effectiveness_result": (
                "ALTER TABLE dofs ADD COLUMN effectiveness_result VARCHAR(40)"
            ),
            "effectiveness_note": "ALTER TABLE dofs ADD COLUMN effectiveness_note TEXT",
            "effectiveness_checked_by_user_id": (
                "ALTER TABLE dofs ADD COLUMN effectiveness_checked_by_user_id INTEGER"
            ),
            "effectiveness_checked_at": (
                "ALTER TABLE dofs ADD COLUMN effectiveness_checked_at DATETIME"
            ),
        }
        for column_name, statement in dof_capa_columns.items():
            if column_name not in columns:
                db.session.execute(text(statement))
                changed = True
        db.session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_dofs_effectiveness_owner_user_id "
                "ON dofs (effectiveness_owner_user_id)"
            )
        )

    if changed:
        db.session.commit()

    tables = set(inspect(db.engine).get_table_names())
    if "actions" in tables and "action_closure_files" in tables:
        columns = {
            column["name"] for column in inspect(db.engine).get_columns("actions")
        }
        if {
            "closure_file_original_name",
            "closure_file_stored_name",
            "closure_file_mime_type",
        }.issubset(columns):
            db.session.execute(
                text(
                    """
                    INSERT INTO action_closure_files
                        (action_id, original_name, stored_name, mime_type, created_at)
                    SELECT
                        id,
                        closure_file_original_name,
                        closure_file_stored_name,
                        closure_file_mime_type,
                        CURRENT_TIMESTAMP
                    FROM actions
                    WHERE closure_file_stored_name IS NOT NULL
                      AND closure_file_original_name IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1
                          FROM action_closure_files
                          WHERE action_closure_files.action_id = actions.id
                            AND action_closure_files.stored_name = actions.closure_file_stored_name
                      )
                    """
                )
            )
            db.session.commit()

    tables = set(inspect(db.engine).get_table_names())
    if "orientation_nodes" in tables:
        columns = {
            column["name"] for column in inspect(db.engine).get_columns("orientation_nodes")
        }
        if "node_type" in columns:
            db.session.execute(
                text(
                    "UPDATE orientation_nodes SET node_type = 'person' "
                    "WHERE node_type IS NULL OR node_type = ''"
                )
            )
            db.session.commit()
        if "color" in columns:
            db.session.execute(
                text(
                    "UPDATE orientation_nodes SET color = '#198754' "
                    "WHERE color IS NULL OR color = ''"
                )
            )
            db.session.commit()

    tables = set(inspect(db.engine).get_table_names())
    if "actions" in tables:
        columns = {
            column["name"] for column in inspect(db.engine).get_columns("actions")
        }
        if "action_number" in columns:
            db.session.execute(
                text("UPDATE actions SET action_number = id WHERE action_number IS NULL")
            )
            db.session.commit()

    tables = set(inspect(db.engine).get_table_names())
    if "actions" in tables and "app_settings" in tables:
        max_number = db.session.execute(
            text("SELECT COALESCE(MAX(COALESCE(action_number, id)), 0) FROM actions")
        ).scalar()
        next_number = max_number + 1
        current_value = db.session.execute(
            text("SELECT value FROM app_settings WHERE key = 'next_action_number'")
        ).scalar()
        if current_value is None:
            db.session.execute(
                text(
                    "INSERT INTO app_settings (key, value) "
                    "VALUES ('next_action_number', :value)"
                ),
                {"value": str(next_number)},
            )
            db.session.commit()
        elif int(current_value) <= max_number:
            db.session.execute(
                text(
                    "UPDATE app_settings SET value = :value "
                    "WHERE key = 'next_action_number'"
                ),
                {"value": str(next_number)},
            )
            db.session.commit()

    tables = set(inspect(db.engine).get_table_names())
    if "dofs" in tables:
        columns = {
            column["name"] for column in inspect(db.engine).get_columns("dofs")
        }
        if {"approval_step", "status"}.issubset(columns):
            db.session.execute(
                text(
                    """
                    UPDATE dofs
                    SET approval_step = 'management_representative',
                        status = 'Onay Akışı Bekleniyor'
                    WHERE status IS NOT NULL
                      AND status != 'Taslak'
                      AND (approval_step IS NULL OR approval_step = 'draft')
                    """
                )
            )
            db.session.commit()

    tables = set(inspect(db.engine).get_table_names())
    if "app_settings" in tables:
        from .legal import ensure_legal_schema

        ensure_legal_schema()
        for readiness_key in (
            "sales_readiness:audit_log",
            "sales_readiness:iso_dashboard",
            "sales_readiness:risk_module",
            "sales_readiness:month3_risk",
            "sales_readiness:training_module",
            "sales_readiness:month3_training",
            "sales_readiness:complaint_module",
            "sales_readiness:month3_complaints",
            "sales_readiness:management_review",
            "sales_readiness:month3_management_review",
            "sales_readiness:supplier_module",
            "sales_readiness:month3_supplier",
            "sales_readiness:month4_tenant_tests",
            "sales_readiness:month4_company_package",
            "sales_readiness:month4_backup",
            "sales_readiness:month4_legal",
            "sales_readiness:month4_admin_panel",
            "sales_readiness:report_center",
            "sales_readiness:month2_reports",
            "sales_readiness:notification_upgrade",
            "sales_readiness:onboarding_wizard",
            "sales_readiness:core_package",
            "sales_readiness:optional_production_modules",
            "sales_readiness:suggestion_core",
            "sales_readiness:module_based_menu",
            "sales_readiness:demo_data_split",
            "sales_readiness:month1_tests",
            "sales_readiness:month1_sqlite",
            "sales_readiness:month1_bugfix",
            "sales_readiness:month1_ui_standard",
            "sales_readiness:month1_tasks",
            "sales_readiness:month2_audit_log",
            "sales_readiness:month2_document_read",
            "sales_readiness:month2_capa_fields",
            "sales_readiness:month2_management_dashboard",
            "sales_readiness:competitor_incident_near_miss",
            "sales_readiness:competitor_fmea",
            "sales_readiness:competitor_process_bpm",
        ):
            db.session.execute(
                text(
                    "INSERT OR IGNORE INTO app_settings (key, value) "
                    "VALUES (:key, '1')"
                ),
                {"key": readiness_key},
            )
        db.session.commit()


def ensure_default_companies():
    for item in DEFAULT_COMPANIES:
        company = Company.query.filter_by(code=item["code"]).first()
        if company is None:
            company = Company(code=item["code"])
            db.session.add(company)
        company.name = item["name"]
        company.package_key = item.get("package_key", "production_plus")
        company.is_demo = bool(item.get("is_demo", False))
        company.is_active = True
    db.session.flush()


def ensure_default_users(reset_passwords=True):
    ensure_runtime_schema()
    ensure_default_companies()
    primary_company = Company.query.filter_by(code=PRIMARY_COMPANY_CODE).first()
    from .company_onboarding import initialize_company_workspace

    for company in Company.query.filter_by(is_active=True).all():
        initialize_company_workspace(company)
    db.session.flush()

    user_columns = {
        column["name"] for column in inspect(db.engine).get_columns("users")
    }
    users_have_company_id = "company_id" in user_columns
    role_by_key = ensure_default_roles()
    role_assignments_initialized = (
        db.session.get(AppSetting, DEFAULT_ROLE_ASSIGNMENT_MARKER) is not None
    )

    for item in DEFAULT_USERS:
        user_query = User.query.filter_by(username=item["username"])
        if users_have_company_id:
            if item["username"] in ADMIN_USERNAMES:
                user_query = user_query.filter(User.company_id.is_(None))
            elif primary_company is not None:
                user_query = user_query.filter_by(company_id=primary_company.id)
        user = user_query.first()
        is_new_user = user is None
        if user is None:
            user = User(username=item["username"])
            db.session.add(user)
            user.full_name = item["full_name"]
            user.title = item["title"]
            user.email = item["email"]
            user.is_active = True

            for permission, value in item["permissions"].items():
                setattr(user, permission, value)

            user.set_password(item["password"])
        elif user.username == "oguzhan":
            user.title = item["title"]

        if user.username in ADMIN_USERNAMES:
            if users_have_company_id:
                user.company_id = None
            user.is_active = True
            for permission, value in item["permissions"].items():
                if value:
                    setattr(user, permission, True)
        elif (
            users_have_company_id
            and primary_company is not None
            and user.company_id is None
        ):
            user.company_id = primary_company.id

        item_roles = item.get("roles") or ()
        should_apply_default_roles = (
            is_new_user
            or user.username in ADMIN_USERNAMES
            or (not role_assignments_initialized and not user.roles)
        )
        if should_apply_default_roles:
            for role_key in item_roles:
                role = role_by_key.get(role_key)
                if role and role not in user.roles:
                    user.roles.append(role)
            sync_seed_legacy_permissions(user)

        if reset_passwords and not user.password_hash:
            user.set_password(item["password"])

    if not role_assignments_initialized:
        db.session.add(AppSetting(key=DEFAULT_ROLE_ASSIGNMENT_MARKER, value="1"))

    db.session.commit()


def ensure_role_permission(role, permission_key):
    db.session.execute(
        text(
            "INSERT OR IGNORE INTO role_permissions (role_id, permission_key) "
            "VALUES (:role_id, :permission_key)"
        ),
        {"role_id": role.id, "permission_key": permission_key},
    )


def ensure_default_role_row(definition):
    role = Role.query.filter_by(key=definition["key"]).first()
    is_new_role = role is None
    if role is None:
        db.session.execute(
            text(
                """
                INSERT OR IGNORE INTO roles
                    (key, name, description, hierarchy_level, is_system)
                VALUES
                    (:key, :name, :description, :hierarchy_level, 1)
                """
            ),
            {
                "key": definition["key"],
                "name": definition["name"],
                "description": definition.get("description"),
                "hierarchy_level": definition["hierarchy_level"],
            },
        )
        db.session.flush()
        role = Role.query.filter_by(key=definition["key"]).first()
    return role, is_new_role


def ensure_default_roles():
    role_by_key = {}
    active_role_keys = {definition["key"] for definition in ROLE_DEFINITIONS}
    for definition in ROLE_DEFINITIONS:
        role, is_new_role = ensure_default_role_row(definition)
        role.name = definition["name"]
        role.description = definition.get("description")
        role.hierarchy_level = definition["hierarchy_level"]
        role.is_system = True

        existing_permissions = {item.permission_key: item for item in role.permissions}
        desired_permissions = set(definition.get("permissions") or ())
        if is_new_role or role.is_system:
            for permission_key in desired_permissions:
                if permission_key not in existing_permissions:
                    ensure_role_permission(role, permission_key)
        if role.key == "super_admin":
            for permission in list(role.permissions):
                if permission.permission_key not in desired_permissions:
                    role.permissions.remove(permission)
        role_by_key[role.key] = role

    db.session.flush()
    for role in role_by_key.values():
        db.session.expire(role, ["permissions"])
    for old_role_key, new_role_key in REMOVED_ROLE_MAPPINGS.items():
        old_role = Role.query.filter_by(key=old_role_key).first()
        new_role = role_by_key.get(new_role_key)
        if old_role is None:
            continue
        if new_role is not None:
            for user in list(old_role.users):
                if new_role not in user.roles:
                    user.roles.append(new_role)
                if old_role in user.roles:
                    user.roles.remove(old_role)
        old_role.is_system = False

    for role in Role.query.all():
        if role.key not in active_role_keys and role.key not in REMOVED_ROLE_MAPPINGS:
            role.is_system = False

    db.session.flush()
    return role_by_key


def ensure_default_maintenance_machines():
    from .routes import ensure_maintenance_schema

    ensure_maintenance_schema()
    changed = False
    for item in MAINTENANCE_MACHINE_DEFAULTS:
        code = item["code"]
        machine = MaintenanceMachine.query.filter_by(code=code).first()
        if machine is None:
            machine = MaintenanceMachine(
                code=code,
                machine_name=item["machine_name"],
                brand_model=item.get("brand_model") or None,
                serial_no=item.get("serial_no") or None,
                status=item.get("status") or "ÇALIŞIYOR",
                location=item.get("location") or None,
                is_active=True,
            )
            db.session.add(machine)
            changed = True
            continue

        for key in ("machine_name", "brand_model", "serial_no", "status", "location"):
            if getattr(machine, key):
                continue
            value = item.get(key) or None
            if key == "status":
                value = item.get(key) or "ÇALIŞIYOR"
            if value:
                setattr(machine, key, value)
                changed = True

    if changed:
        db.session.commit()

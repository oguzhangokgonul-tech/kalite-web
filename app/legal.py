from datetime import date, datetime

from flask import current_app
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from .audit import record_audit_event
from .extensions import db
from .models import (
    CompanyLegalProfile,
    LegalAcceptance,
    LegalDocument,
    LEGAL_DOCUMENT_TYPES,
)


LEGAL_POLICY_VERSION = "2026.09"


def repair_mojibake(value):
    if not isinstance(value, str):
        return value
    try:
        return value.encode("cp1252").decode("utf-8")
    except UnicodeError:
        return value


LEGAL_DOCUMENT_TYPES_NORMALIZED = tuple(
    {**item, "title": repair_mojibake(item.get("title", ""))}
    for item in LEGAL_DOCUMENT_TYPES
)
LEGAL_DOCUMENT_TYPE_MAP = {item["key"]: item for item in LEGAL_DOCUMENT_TYPES_NORMALIZED}
LEGAL_DOCUMENT_SLUG_MAP = {item["slug"]: item for item in LEGAL_DOCUMENT_TYPES_NORMALIZED}

RAW_DEFAULT_LEGAL_CONTENT = {
    "terms": """Bu metin VolkaPortal satış hazırlığı için hazırlanmış taslak kullanım şartlarıdır. Nihai yayından önce hukuki danışman onayı alınmalıdır.

1. Hizmetin Kapsamı
VolkaPortal; aksiyon, doküman, IF/DÖF, iç denetim, kalibrasyon, eğitim, risk, tedarikçi ve ilgili kalite yönetim kayıtlarının takip edilmesi için sunulan bir SaaS kalite yönetim platformudur.

2. Hesap ve Yetki Sorumluluğu
Kullanıcılar hesap bilgilerinin güvenliğinden, kendilerine verilen yetkilerle yaptıkları işlemlerden ve sisteme girdikleri kayıtların doğruluğundan sorumludur. Firma yöneticileri kullanıcı yetkilerini güncel tutmalıdır.

3. Müşteri Verileri
Sisteme girilen firma, personel, doküman, kalite kaydı ve dosyalar ilgili müşteri şirketin verisidir. VolkaPortal bu verileri hizmeti sağlamak, güvenliği korumak, yedekleme yapmak ve destek vermek amacıyla işler.

4. Kabul Edilebilir Kullanım
Sisteme hukuka aykırı, yetkisiz, zararlı, kişisel hakları ihlal eden veya kalite yönetim amacıyla ilgisiz veri yüklenmemelidir.

5. Hizmet Sürekliliği ve Bakım
Planlı bakım, güvenlik güncellemesi veya teknik zorunluluk durumlarında hizmette geçici kesinti olabilir. Kritik güncellemelerden önce yedekleme prosedürü uygulanır.

6. Sorumluluk Sınırı
VolkaPortal kayıtların tutulmasına yardımcı olur; nihai kalite yönetim kararları, mevzuat uyumu ve denetim sorumluluğu müşteri şirkete aittir.""",
    "privacy": """Bu metin VolkaPortal satış hazırlığı için hazırlanmış taslak gizlilik politikasıdır. Nihai yayından önce hukuki danışman onayı alınmalıdır.

1. İşlenen Veri Kategorileri
Kullanıcı kimlik bilgileri, iletişim bilgileri, firma bilgileri, giriş kayıtları, yetki kayıtları, işlem/audit kayıtları, yüklenen dosyalar ve kalite yönetim süreçlerinde girilen içerikler işlenebilir.

2. İşleme Amaçları
Veriler; kullanıcı doğrulama, yetkilendirme, kalite yönetim süreçlerini yürütme, bildirim gönderme, güvenlik, denetim kanıtı, yedekleme, destek ve hizmet iyileştirme amaçlarıyla işlenir.

3. Saklama
Kayıtlar hizmet süresince ve sözleşme, kalite standardı, denetim veya yasal saklama yükümlülükleri gerektirdiği ölçüde saklanır. Teknik yedekler sınırlı sayıda tutulur.

4. Paylaşım
Veriler kural olarak müşteri şirket kapsamı içinde kullanılır. Barındırma, e-posta, yedekleme veya teknik destek sağlayıcıları gibi hizmet sağlayıcılarla gerekli olduğu ölçüde paylaşım yapılabilir.

5. Güvenlik
Yetki kontrolü, şirket bazlı veri izolasyonu, audit log, dosya güvenliği, yedek doğrulama ve oturum güvenliği gibi teknik tedbirler uygulanır.

6. Haklar
Kullanıcılar ve ilgili kişiler, geçerli mevzuat kapsamındaki bilgi alma, erişim, düzeltme, silme veya işleme itiraz hakları için kendi şirket yetkilisine veya belirtilen iletişim adresine başvurabilir.""",
    "kvkk": """Bu metin VolkaPortal satış hazırlığı için hazırlanmış taslak KVKK aydınlatma metnidir. Nihai yayından önce hukuki danışman onayı alınmalıdır.

1. Veri Sorumlusu ve Veri İşleyen Ayrımı
VolkaPortal, müşteri şirketlerin kalite yönetim süreçlerini yürüttüğü bir platformdur. Müşteri şirket, kendi çalışanları ve süreç kayıtları açısından veri sorumlusu olabilir. VolkaPortal hizmet sağlayıcı/platform işletmecisi olarak teknik altyapı ve destek kapsamında veri işleyebilir.

2. Kişisel Veriler
Ad soyad, kullanıcı adı, e-posta, telefon, görev/unvan, departman, işlem kayıtları, IP adresi, kullanıcı ajanı, bildirim kayıtları, yüklenen dosyalardaki bilgiler ve kalite süreçlerindeki açıklamalar işlenebilir.

3. İşleme Amaçları
Kalite yönetim süreçlerinin yürütülmesi, kullanıcı ve yetki yönetimi, denetim kanıtı oluşturulması, doküman ve aksiyon takibi, bildirim, güvenlik, yedekleme ve teknik destek amaçlarıyla veri işlenir.

4. Aktarım
Veriler; barındırma, e-posta gönderimi, yedekleme ve teknik destek hizmetleri için gerekli hizmet sağlayıcılarla, sözleşme ve mevzuat sınırları içinde paylaşılabilir.

5. Toplama Yöntemi ve Hukuki Sebep
Veriler elektronik formlar, dosya yükleme alanları, kullanıcı işlemleri ve sistem logları üzerinden toplanır. Hukuki sebepler; sözleşmenin kurulması/ifası, meşru menfaat, hukuki yükümlülük ve açık rıza gerektiren hallerde rıza olabilir.

6. İlgili Kişi Hakları
İlgili kişiler KVKK kapsamındaki haklarını kullanmak için şirket yetkilisine veya KVKK iletişim adresine başvurabilir.""",
    "retention": """Bu metin VolkaPortal satış hazırlığı için hazırlanmış taslak veri saklama politikasıdır. Nihai yayından önce hukuki danışman onayı alınmalıdır.

1. Aktif Kayıtlar
Kalite yönetim kayıtları, dokümanlar, aksiyonlar, IF/DÖF kayıtları, eğitim, denetim ve kalibrasyon kayıtları hizmet kullanımı devam ettiği sürece saklanır.

2. Pasif ve Silinmiş Kayıtlar
Sistemde silme işlemleri mümkün olduğunca soft-delete veya arşiv mantığıyla yürütülür. Denetim kanıtı gerektiren kayıtlar tamamen yok edilmeden önce yasal ve sözleşmesel yükümlülükler kontrol edilmelidir.

3. Audit Log
Audit log kayıtları kim, neyi, ne zaman değiştirdi bilgisini içerir. ISO 9001 ve denetim kanıtı ihtiyacı nedeniyle bu kayıtlar uzun süreli saklama politikasına tabidir.

4. Dosyalar ve Arşivler
Yüklenen dokümanlar, revizyon arşivleri ve kanıt dosyaları ilgili kayıtla birlikte saklanır. Eski doküman revizyonları silinmek yerine arşivde tutulur.

5. Yedekler
Tam sistem yedekleri `FULL_BACKUP_KEEP_LAST`, veritabanı yedekleri `DATABASE_BACKUP_KEEP_LAST` ayarlarına göre sınırlı sayıda saklanır. Yedek doğrulaması checksum ve SQLite bütünlük kontrolüyle yapılır.

6. Sözleşme Sonu
Müşteri ilişkisinin sona ermesi halinde veri dışa aktarma, arşivleme, silme veya anonimleştirme süreci sözleşme ve mevzuata göre ayrıca yürütülür.""",
}

DEFAULT_LEGAL_CONTENT = {
    key: repair_mojibake(value)
    for key, value in RAW_DEFAULT_LEGAL_CONTENT.items()
}


def ensure_legal_schema():
    if current_app.extensions.get("legal_schema_checked"):
        return

    try:
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        with db.engine.begin() as connection:
            if "legal_documents" not in tables:
                connection.execute(
                    text(
                        """
                        CREATE TABLE legal_documents (
                            id INTEGER NOT NULL PRIMARY KEY,
                            document_type VARCHAR(40) NOT NULL,
                            slug VARCHAR(80) NOT NULL,
                            title VARCHAR(160) NOT NULL,
                            version VARCHAR(40) NOT NULL,
                            content TEXT NOT NULL,
                            status VARCHAR(20) NOT NULL DEFAULT 'draft',
                            effective_date DATE,
                            published_at DATETIME,
                            published_by_user_id INTEGER,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY(published_by_user_id) REFERENCES users (id),
                            UNIQUE (document_type, version)
                        )
                        """
                    )
                )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_legal_documents_document_type "
                    "ON legal_documents (document_type)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_legal_documents_slug "
                    "ON legal_documents (slug)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_legal_documents_status "
                    "ON legal_documents (status)"
                )
            )

            if "legal_acceptances" not in tables:
                connection.execute(
                    text(
                        """
                        CREATE TABLE legal_acceptances (
                            id INTEGER NOT NULL PRIMARY KEY,
                            company_id INTEGER,
                            user_id INTEGER NOT NULL,
                            legal_document_id INTEGER NOT NULL,
                            document_type VARCHAR(40) NOT NULL,
                            version VARCHAR(40) NOT NULL,
                            accepted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            ip_address VARCHAR(80),
                            user_agent VARCHAR(255),
                            FOREIGN KEY(company_id) REFERENCES companies (id),
                            FOREIGN KEY(user_id) REFERENCES users (id),
                            FOREIGN KEY(legal_document_id) REFERENCES legal_documents (id),
                            UNIQUE (user_id, company_id, legal_document_id, version)
                        )
                        """
                    )
                )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_legal_acceptances_company_id "
                    "ON legal_acceptances (company_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_legal_acceptances_user_id "
                    "ON legal_acceptances (user_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_legal_acceptances_legal_document_id "
                    "ON legal_acceptances (legal_document_id)"
                )
            )

            if "company_legal_profiles" not in tables:
                connection.execute(
                    text(
                        """
                        CREATE TABLE company_legal_profiles (
                            company_id INTEGER NOT NULL PRIMARY KEY,
                            legal_name VARCHAR(255),
                            legal_address TEXT,
                            tax_number VARCHAR(80),
                            mersis_number VARCHAR(80),
                            kvkk_contact_email VARCHAR(255),
                            data_controller_name VARCHAR(255),
                            dpo_contact VARCHAR(255),
                            updated_by_user_id INTEGER,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY(company_id) REFERENCES companies (id),
                            FOREIGN KEY(updated_by_user_id) REFERENCES users (id)
                        )
                        """
                    )
                )
        current_app.extensions["legal_schema_checked"] = True
        ensure_default_legal_documents()
    except OperationalError:
        db.session.rollback()
        current_app.logger.exception("Legal sema kontrol edilemedi.")


def legal_type_by_slug(slug):
    return LEGAL_DOCUMENT_SLUG_MAP.get(slug)


def legal_type_by_key(document_type):
    return LEGAL_DOCUMENT_TYPE_MAP.get(document_type)


def legal_type_choices():
    return sorted(LEGAL_DOCUMENT_TYPES_NORMALIZED, key=lambda item: item["sort_order"])


def ensure_default_legal_documents():
    for item in legal_type_choices():
        existing = LegalDocument.query.filter_by(
            document_type=item["key"],
            version=LEGAL_POLICY_VERSION,
        ).first()
        if existing is not None:
            continue
        document = LegalDocument(
            document_type=item["key"],
            slug=item["slug"],
            title=item["title"],
            version=LEGAL_POLICY_VERSION,
            content=DEFAULT_LEGAL_CONTENT[item["key"]],
            status="published",
            effective_date=date(2026, 9, 7),
            published_at=datetime.now(),
        )
        db.session.add(document)
    db.session.commit()


def published_legal_documents():
    ensure_legal_schema()
    documents = (
        LegalDocument.query.filter_by(status="published")
        .order_by(LegalDocument.document_type.asc(), LegalDocument.id.desc())
        .all()
    )
    latest_by_type = {}
    for document in documents:
        latest_by_type.setdefault(document.document_type, document)
    return [
        latest_by_type[item["key"]]
        for item in legal_type_choices()
        if item["key"] in latest_by_type
    ]


def published_document_for_slug(slug):
    item = legal_type_by_slug(slug)
    if item is None:
        return None
    ensure_legal_schema()
    return (
        LegalDocument.query.filter_by(
            document_type=item["key"],
            status="published",
        )
        .order_by(LegalDocument.published_at.desc(), LegalDocument.id.desc())
        .first()
    )


def acceptance_company_id(user, company=None):
    if company is not None:
        return company.id
    return getattr(user, "company_id", None)


def accepted_document_ids_for_user(user, company_id, documents):
    if not user or not documents:
        return set()
    query = LegalAcceptance.query.filter(
        LegalAcceptance.user_id == user.id,
        LegalAcceptance.legal_document_id.in_([document.id for document in documents]),
    )
    if company_id is None:
        query = query.filter(LegalAcceptance.company_id.is_(None))
    else:
        query = query.filter(LegalAcceptance.company_id == company_id)
    return {
        (acceptance.legal_document_id, acceptance.version)
        for acceptance in query.all()
    }


def pending_legal_documents_for_user(user, company=None):
    documents = published_legal_documents()
    company_id = acceptance_company_id(user, company)
    accepted = accepted_document_ids_for_user(user, company_id, documents)
    return [
        document
        for document in documents
        if (document.id, document.version) not in accepted
    ]


def user_needs_legal_acceptance(user, company=None):
    if not current_app.config.get("LEGAL_ACCEPTANCE_REQUIRED", False):
        return False
    return bool(pending_legal_documents_for_user(user, company))


def record_legal_acceptances(user, company=None, ip_address=None, user_agent=None):
    documents = pending_legal_documents_for_user(user, company)
    company_id = acceptance_company_id(user, company)
    for document in documents:
        db.session.add(
            LegalAcceptance(
                company_id=company_id,
                user_id=user.id,
                legal_document_id=document.id,
                document_type=document.document_type,
                version=document.version,
                ip_address=(ip_address or "")[:80] or None,
                user_agent=(user_agent or "")[:255] or None,
            )
        )
        record_audit_event(
            "LegalAcceptance",
            "legal_acceptance_recorded",
            f"{user.full_name or user.username} legal metni kabul etti",
            entity_id=document.id,
            details={
                "document_type": document.document_type,
                "version": document.version,
                "company_id": company_id,
            },
            company_id=company_id,
            user_id=user.id,
            commit=False,
        )
    db.session.commit()
    return documents


def company_legal_profile_for(company, create=False):
    if company is None:
        return None
    profile = CompanyLegalProfile.query.filter_by(company_id=company.id).first()
    if profile is None and create:
        profile = CompanyLegalProfile(
            company_id=company.id,
            legal_name=company.name,
            data_controller_name=company.name,
        )
        db.session.add(profile)
        db.session.flush()
    return profile


def legal_public_context(company=None):
    profile = company_legal_profile_for(company) if company is not None else None
    return {
        "company": company,
        "legal_profile": profile,
        "provider_name": current_app.config.get("LEGAL_PROVIDER_NAME")
        or current_app.config.get("SITE_NAME", "VolkaPortal"),
        "provider_contact_email": current_app.config.get("LEGAL_CONTACT_EMAIL", ""),
        "documents": published_legal_documents(),
        "legal_types": legal_type_choices(),
    }

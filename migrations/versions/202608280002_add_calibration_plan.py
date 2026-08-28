"""add calibration plan module

Revision ID: 202608280002
Revises: 202608280001
Create Date: 2026-08-28
"""

from datetime import date, timedelta

from alembic import op
import sqlalchemy as sa


revision = "202608280002"
down_revision = "202608280001"
branch_labels = None
depends_on = None


CALIBRATION_ROWS = (
    ("CK01", "METAL TEL ÖRGÜLÜ ELEK", "KALİTE LTD", "125 um", "04.03.408", "125 um", "± 12,4 um", "LAB.", "0064K-1225-00223", "29.11.2025", "1 YIL", "29.11.2026", "UYGUN"),
    ("CK02", "METAL TEL ÖRGÜLÜ ELEK", "BAZ MAKİNA", "250 um", "BZ015", "250 um", "± 25,3 um", "LAB.", "0064K-1225-00224", "29.11.2025", "1 YIL", "29.11.2026", "UYGUN"),
    ("CK03", "METAL TEL ÖRGÜLÜ ELEK", "KALİTE LTD", "500 um", "04.03.412", "500 um", "± 68,8 um", "LAB.", "0064K-1225-00225", "29.11.2025", "1 YIL", "29.11.2026", "UYGUN"),
    ("CK04", "METAL TEL ÖRGÜLÜ ELEK", "BAZ MAKİNA", "1 mm", "BZ006", "1 mm", "± 0,032mm", "LAB.", "0064K-1225-00226", "29.11.2025", "1 YIL", "29.11.2026", "UYGUN"),
    ("CK05", "METAL TEL ÖRGÜLÜ ELEK", "BAZ MAKİNA", "2 mm", "BZ010", "2 mm", "± 0,047 mm", "LAB.", "0064K-1225-00227", "29.11.2025", "1 YIL", "29.11.2026", "UYGUN"),
    ("CK06", "METAL TEL ÖRGÜLÜ ELEK", "KALİTE LTD", "4 mm", "30574", "4 mm", "± 0,250 mm", "LAB.", "0064K-1225-00228", "29.11.2025", "1 YIL", "29.11.2026", "UYGUN"),
    ("CK07", "METAL TEL ÖRGÜLÜ ELEK", "BAZ MAKİNA", "5,6 mm", "100030147", "5,6 mm", "± 0,130 mm", "LAB.", "0064K-1225-00229", "45990", "1 YIL", "46355", "UYGUN"),
    ("CK08", "METAL TEL ÖRGÜLÜ ELEK", "KALİTE LTD", "8 mm", "30576", "8 mm", "± 0,300 mm", "LAB.", "0064K-1225-00230", "45990", "1 YIL", "46355", "UYGUN"),
    ("CK09", "METAL TEL ÖRGÜLÜ ELEK", "BAZ MAKİNA", "11,2 mm", "BZ011", "11,2 mm", "± 0,330 mm", "LAB.", "0064K-1225-00231", "45990", "1 YIL", "46355", "UYGUN"),
    ("CK10", "METAL TEL ÖRGÜLÜ ELEK", "BAZ MAKİNA", "16 mm", "BZ012", "16 mm", "± 0,23 mm", "LAB.", "0064K-1225-00232", "45990", "1 YIL", "46355", "UYGUN"),
    ("CK11", "GÖSTERGELİ SICAKLIK ÖLÇER", "TESTO", "826-T4", "31503132", "-50+230 °C", "-0,2 °C", "LAB.", "0064K-1225-00233", "45990", "1 YIL", "46355", "UYGUN"),
    ("CK12", "METAL TEL ÖRGÜLÜ ELEK", "BAZ MAKİNA", "22,4 mm", "BZ013", "22,4 mm", "± 0,260 mm", "LAB.", "0064K-1225-00234", "45990", "1 YIL", "46355", "UYGUN"),
    ("CK13", "METAL TEL ÖRGÜLÜ ELEK", "KALİTE LTD", "31,5 mm", "30572", "31,5 mm", "± 0,470 mm", "LAB.", "0064K-1225-00235", "29.11.2025", "1 YIL", "29.11.2026", "UYGUN"),
    ("CK14", "BETON TEST PRESİ", "ÇELİK MAKİNA", "CMS", "45962", "0-3000 kN", "± % 0,83", "LAB.", "0064K-1225-00305", "19.11.2025", "1 YIL", "19.11.2026", "UYGUN"),
    ("CK15", "BETON NUMUNE KALIBI", "-", "150x150 mm (6adet)", "64K-1225-0030", "150 mm", "± 0,42 mm", "LAB.", "0064K-1225-00306", "19.11.2025", "1 YIL", "19.11.2026", "UYGUN"),
    ("CK16", "METİLEN MAVİSİ KARIŞTIRICISI", "LABORTEK", "100031147", "100031147", "400-600 rpm", "-5,5 rpm", "LAB.", "0064K-1225-00307", "19.11.2025", "1 YIL", "19.11.2026", "UYGUN"),
    ("CK17", "TERAZİ", "DENSİ", "DS-20", "6737", "0-20 kg", "-1,0 g", "LAB.", "0064K-1225-00308", "19.11.2025", "1 YIL", "19.11.2026", "UYGUN"),
    ("CK18", "SICAKLIK KABİNİ (ETÜV)", "BAZ MAKİNA", "LAE (LTW12)", "19001780", "0-110 °C", ".-1 °C", "LAB.", "0064K-1225-00309", "19.11.2025", "1 YIL", "19.11.2026", "UYGUN"),
    ("CK19", "TERAZİ", "DİKOMSAN", "EHB", "114062694", "0-1000 g", "-0,01 g", "LAB.", "0064K-1225-00400", "19.11.2025", "1 YIL", "19.11.2026", "UYGUN"),
    ("CK20", "MEZÜR", "SH LABWERE", "A", "MZ-2", "500 mL", "± 1mL", "LAB.", "0068K-1225-04104", "18.12.2025", "1 YIL", "18.12.2026", "UYGUN"),
    ("CK21", "BETON NUMUNE KALIBI", "LİYA", "150 mm Küp", "100030139", "150x150 mm", "± 0,03 mm", "LAB.", "0068K-1225-04105", "18.12.2025", "1 YIL", "18.12.2026", "UYGUN"),
    ("CK22", "BETON NUMUNE KALIBI", "LİYA", "150 mm Küp", "100030140", "150x150 mm", "± 0,03 mm", "LAB.", "0068K-1225-04106", "18.12.2025", "1 YIL", "18.12.2026", "UYGUN"),
    ("CK23", "ELEK", "LİYA", "63 um", "ELK-1", "63 um", "± 0,010 mm", "LAB.", "0068K-1225-04096", "18.12.2025", "1 YIL", "18.12.2026", "UYGUN"),
    ("CK24", "ELEK", "LİYA", "63 um", "ELK-2", "63 um", "± 0,0195 mm", "LAB.", "0068K-1225-04095", "18.12.2025", "1 YIL", "18.12.2026", "UYGUN"),
    ("CK25", "BEHER", "-", "-", "BH-1", "250mL", "± 0,38 mm", "LAB.", "K518120901", "18.12.2025", "1 YIL", "18.12.2026", "UYGUN"),
    ("CK26", "BEHER", "-", "-", "BH-2", "600mL", "± 0,38 mm", "LAB.", "K518120902", "18.12.2025", "1 YIL", "18.12.2026", "UYGUN"),
    ("CK27", "BEHER", "-", "-", "BH-3", "1000mL", "± 0,38 mm", "LAB.", "K518120903", "18.12.2025", "1 YIL", "18.12.2026", "UYGUN"),
    ("CK28", "MEZÜR", "SH LABWERE", "A", "MZ-3", "1000 mL", "± 0,49 mm", "LAB.", "K518120904", "18.12.2025", "1 YIL", "18.12.2026", "UYGUN"),
    ("CK29", "DANSİMETRE", "BOLİFUJİ", "-", "212365 / HS-014", "1000-1100 g/cm3", "2", "LAB.", "K518120905", "18.12.2025", "1 YIL", "18.12.2026", "UYGUN"),
    ("CK30", "DANSİMETRE", "GREINORM", "-", "90001607 / HS-013", "1100-1200 g/cm3 ", "2", "LAB.", "K518120906", "18.12.2025", "1 YIL", "18.12.2026", "UYGUN"),
    ("CK31", "PİKNOMETRE", "-", "A", "PK-1", "1000mL", "0.26", "LAB.", "K518120907", "18.12.2025", "1 YIL", "18.12.2026", "UYGUN"),
    ("CK32", "PİKNOMETRE", "-", "A", "PK-2", "3000mL", "0.06", "LAB.", "K518120908", "18.12.2025", "1 YIL", "18.12.2026", "UYGUN"),
    ("CK33", "MİN.-MAX. HAVA TERMOMETRESİ", "-", "HTC-1", "SNÖ-1", "0-99%rh -50 / 70 °C", ".+3 %rh / 0,1 °C", "LAB.", "0068K-1225-04094", "18.12.2025", "1 YIL", "18.12.2026", "UYGUN"),
    ("CK34", "DİJİTAL TERMOMETRE", "-", "TP-101", "TM-01", ".-50/300°C", "± 0,31 °C", "LAB.", "0068K-1225-04087", "18.12.2025", "1 YIL", "18.12.2026", "UYGUN"),
    ("CK35", "DİJİTAL TERMOMETRE", "-", "TP-101", "TM-02", ".-50/300°C", "± 0,41 °C", "LAB.", "0068K-1225-04086", "18.12.2025", "1 YIL", "18.12.2026", "UYGUN"),
    ("CK36", "SENTİL ÇAKISI", "-", "-", "SNT-01", "0,15-1MM", "± 0,0027 mm", "LAB.", "0068K-1225-04108", "18.12.2025", "1 YIL", "18.12.2026", "UYGUN"),
    ("CK37", "MEZÜR", "SH LABWERE", "A", "MZ-1", "500 Ml", "± 0,44mL", "LAB.", "0068K-1225-04101", "18.12.2025", "1 YIL", "18.12.2026", "UYGUN"),
    ("CK38", "GÖNYE", "BTS", "BTS12241", "GNY-01", "300X125 mm", "± 0,20 mm", "LAB.", "0068K-1225-04102", "18.12.2025", "1 YIL", "18.12.2026", "UYGUN"),
    ("CK40", "BETON HAVA ÖLÇER", "ÇELİK MAKİNA", "-", "100031148", "% 0 - 10", "± % 0,6", "LAB.", "4666001", "45980", "1 YIL", "46345", "UYGUN"),
    ("CK41", "KUMPAS", "E", "DİJİTAL", "20083042", "150mm", "0", "LAB.", "0138K-0126-00278", "46034", "1 YIL", "46374", "UYGUN"),
    ("CK42", "ŞERİTMETRE", "FİSCO", "SATELLİTE", "08370", "10000mm", "0", "LAB.", "0138K-0126-00279", "46034", "1 YIL", "46345", "UYGUN"),
    ("CK43", "MANOMETRE", "PAKKENS", "GLİSERİNLİ", "15899", "0 - 600 Bar", "-0,84 bar", "LAB.", "0138K-0326-00285", "46086", "1 YIL", "46451", "UYGUN"),
    ("CK44", "MANOMETRE", "DASTERM", "GLİSERİNLİ", "08081", "0 - 600 Bar", ".-1,06 bar", "LAB.", "0138K-326-00078", "46086", "1 YIL", "46451", "UYGUN"),
    ("CK45", "MANOMETRE", "PAKKENS", "GLİSERİNLİ", "15898", "0 - 600 Bar", ".-1,03 bar", "LAB.", "0138K-0326-00338", "46086", "1 YIL", "46451", "UYGUN"),
    ("CK46", "MANOMETRE", "PAKKENS", "GLİSERİNLİ", "08105", "0 - 600 Bar", ".-1,02 bar", "LAB.", "0138K-0326-00162", "46086", "1 YIL", "46451", "UYGUN"),
    ("CK47", "MANOMETRE", "PAKKENS", "GLİSERİNLİ", "15900", "0 - 600 Bar", ".-0,86 bar", "LAB.", "0138K-0326-00284", "46086", "1 YIL", "46451", "UYGUN"),
    ("CK48", "MANOMETRE", "PAKKENS", "GLİSERİNLİ", "08106", "0 - 600 Bar", ".-1,02 bar", "LAB.", "0138K-0326-00139", "46086", "1 YIL", "46451", "UYGUN"),
    ("CK49", "KUMPAS", "GFB", "DİJİTAL", "KMP-1", "0 - 150mm", "0", "LAB.", "0068K-1225-04103", "46009", "1 YIL", "46374", "UYGUN"),
)


def _table_names(bind):
    return set(sa.inspect(bind).get_table_names())


def _parse_excel_date(value):
    text = str(value or "").strip()
    if not text:
        return None
    if text.replace(".", "", 1).isdigit() and "." not in text:
        return (date(1899, 12, 30) + timedelta(days=int(text))).isoformat()
    day, month, year = text.split(".")
    return date(int(year), int(month), int(day)).isoformat()


def upgrade():
    bind = op.get_bind()
    tables = _table_names(bind)

    if "calibration_records" not in tables:
        op.create_table(
            "calibration_records",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("company_id", sa.Integer(), nullable=True),
            sa.Column("device_code", sa.String(length=80), nullable=False),
            sa.Column("device_name", sa.String(length=220), nullable=False),
            sa.Column("manufacturer", sa.String(length=160), nullable=True),
            sa.Column("brand_model", sa.String(length=180), nullable=True),
            sa.Column("serial_no", sa.String(length=160), nullable=True),
            sa.Column("measurement_range", sa.String(length=160), nullable=True),
            sa.Column("deviation_range", sa.String(length=160), nullable=True),
            sa.Column("location", sa.String(length=160), nullable=True),
            sa.Column("certificate_no", sa.String(length=160), nullable=True),
            sa.Column("calibration_date", sa.Date(), nullable=True),
            sa.Column("calibration_interval", sa.String(length=80), nullable=True),
            sa.Column("next_calibration_date", sa.Date(), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="UYGUN"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("company_id", "device_code", name="uq_calibration_records_company_device_code"),
        )
        op.create_index("ix_calibration_records_company_id", "calibration_records", ["company_id"])
        op.create_index("ix_calibration_records_device_code", "calibration_records", ["device_code"])
        op.create_index("ix_calibration_records_next_date", "calibration_records", ["next_calibration_date"])

    if "company_modules" in _table_names(bind):
        company_ids = [row[0] for row in bind.execute(sa.text("SELECT id FROM companies")).fetchall()]
        for company_id in company_ids:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO company_modules (company_id, module_key, is_enabled)
                    SELECT :company_id, 'calibration', 1
                    WHERE NOT EXISTS (
                        SELECT 1 FROM company_modules
                        WHERE company_id = :company_id AND module_key = 'calibration'
                    )
                    """
                ),
                {"company_id": company_id},
            )

    if "role_permissions" in _table_names(bind) and "roles" in _table_names(bind):
        for role_key in ("super_admin", "management_representative"):
            bind.execute(
                sa.text(
                    """
                    INSERT INTO role_permissions (role_id, permission_key)
                    SELECT roles.id, 'calibration.manage'
                    FROM roles
                    WHERE roles.key = :role_key
                      AND NOT EXISTS (
                        SELECT 1 FROM role_permissions
                        WHERE role_id = roles.id AND permission_key = 'calibration.manage'
                      )
                    """
                ),
                {"role_key": role_key},
            )

    if "companies" not in _table_names(bind):
        return
    company = bind.execute(
        sa.text("SELECT id FROM companies WHERE code = '001' LIMIT 1")
    ).fetchone()
    if company is None:
        company = bind.execute(sa.text("SELECT id FROM companies ORDER BY id LIMIT 1")).fetchone()
    if company is None:
        return
    company_id = company[0]

    insert_sql = sa.text(
        """
        INSERT INTO calibration_records (
            company_id, device_code, device_name, manufacturer, brand_model,
            serial_no, measurement_range, deviation_range, location,
            certificate_no, calibration_date, calibration_interval,
            next_calibration_date, status, is_active
        )
        SELECT
            :company_id, :device_code, :device_name, :manufacturer, :brand_model,
            :serial_no, :measurement_range, :deviation_range, :location,
            :certificate_no, :calibration_date, :calibration_interval,
            :next_calibration_date, :status, 1
        WHERE NOT EXISTS (
            SELECT 1 FROM calibration_records
            WHERE company_id = :company_id AND device_code = :device_code
        )
        """
    )
    for row in CALIBRATION_ROWS:
        bind.execute(
            insert_sql,
            {
                "company_id": company_id,
                "device_code": row[0],
                "device_name": row[1],
                "manufacturer": row[2],
                "brand_model": row[3],
                "serial_no": row[4],
                "measurement_range": row[5],
                "deviation_range": row[6],
                "location": row[7],
                "certificate_no": row[8],
                "calibration_date": _parse_excel_date(row[9]),
                "calibration_interval": row[10],
                "next_calibration_date": _parse_excel_date(row[11]),
                "status": row[12],
            },
        )


def downgrade():
    bind = op.get_bind()
    tables = _table_names(bind)
    if "company_modules" in tables:
        bind.execute(sa.text("DELETE FROM company_modules WHERE module_key = 'calibration'"))
    if "role_permissions" in tables:
        bind.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_key = 'calibration.manage'")
        )
    if "calibration_records" not in tables:
        return
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("calibration_records")}
    for index_name in (
        "ix_calibration_records_next_date",
        "ix_calibration_records_device_code",
        "ix_calibration_records_company_id",
    ):
        if index_name in indexes:
            op.drop_index(index_name, table_name="calibration_records")
    op.drop_table("calibration_records")

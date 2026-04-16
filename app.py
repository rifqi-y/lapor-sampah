import os
from datetime import datetime
import time
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///persampahan.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["ENV"] = os.getenv("FLASK_ENV", "development")

UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ===== S3 CONFIG =====
USE_S3 = os.getenv("USE_S3", "false").lower() == "true"
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "")
S3_UPLOAD_PREFIX = os.getenv("S3_UPLOAD_PREFIX", "uploads/").strip("/")
if S3_UPLOAD_PREFIX:
    S3_UPLOAD_PREFIX = S3_UPLOAD_PREFIX + "/"

s3_client = None
if USE_S3:
    s3_client = boto3.client("s3", region_name=AWS_REGION)

db = SQLAlchemy(app)


# ---- INIT DB SEKALI SAJA (bukan before_request) ----
def init_db():
    with app.app_context():
        db.create_all()


class LaporanSampah(db.Model):
    __tablename__ = "laporan_sampah"
    id = db.Column(db.Integer, primary_key=True)
    judul = db.Column(db.String(120), nullable=False)
    deskripsi = db.Column(db.Text, nullable=False)
    lokasi = db.Column(db.String(255), nullable=False)
    foto = db.Column(db.String(255), nullable=True)  # simpan filename (local) / key (s3)
    status = db.Column(db.String(30), default="Baru")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class JadwalAngkut(db.Model):
    __tablename__ = "jadwal_angkut"
    id = db.Column(db.Integer, primary_key=True)
    wilayah = db.Column(db.String(120), nullable=False)
    tanggal = db.Column(db.Date, nullable=False)
    jam = db.Column(db.String(20), nullable=False)
    keterangan = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(30), default="Terjadwal")

class Petugas(db.Model):
    __tablename__ = "petugas"
    id = db.Column(db.Integer, primary_key=True)
    nama = db.Column(db.String(120), nullable=False)
    area_tugas = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(30), default="Siaga")
    update_terakhir = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

JADWAL_STATUS_OPTIONS = {"Terjadwal", "Berjalan", "Selesai"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def upload_file_storage(file_obj, safe_name):
    """
    return value:
      - local mode: filename
      - s3 mode: object key
    """
    if USE_S3:
        key = f"{S3_UPLOAD_PREFIX}{safe_name}"
        s3_client.upload_fileobj(
            file_obj,
            S3_BUCKET_NAME,
            key,
            ExtraArgs={"ContentType": file_obj.content_type}
        )
        return key
    else:
        file_obj.save(os.path.join(app.config["UPLOAD_FOLDER"], safe_name))
        return safe_name


@app.route("/")
def index():
    total_laporan = LaporanSampah.query.count()
    total_jadwal = JadwalAngkut.query.count()
    total_petugas = Petugas.query.count()

    laporan_baru = LaporanSampah.query.filter_by(status="Baru").count()
    jadwal_hari_ini = JadwalAngkut.query.filter_by(tanggal=datetime.utcnow().date()).count()
    petugas_aktif = Petugas.query.filter(Petugas.status.in_(["Bertugas", "Siaga"])).count()

    return render_template(
        "index.html",
        total_laporan=total_laporan,
        total_jadwal=total_jadwal,
        total_petugas=total_petugas,
        laporan_baru=laporan_baru,
        jadwal_hari_ini=jadwal_hari_ini,
        petugas_aktif=petugas_aktif,
    )


@app.route("/laporan", methods=["GET", "POST"])
def laporan():
    if request.method == "POST":
        judul = request.form.get("judul")
        deskripsi = request.form.get("deskripsi")
        lokasi = request.form.get("lokasi")
        foto_file = request.files.get("foto")

        if not judul or not deskripsi or not lokasi:
            flash("Judul, deskripsi, dan lokasi wajib diisi.", "error")
            return redirect(url_for("laporan"))

        file_ref = None
        if foto_file and foto_file.filename:
            if allowed_file(foto_file.filename):
                safe_name = secure_filename(foto_file.filename)
                safe_name = f"{int(time.time())}_{safe_name}"
                try:
                    file_ref = upload_file_storage(foto_file, safe_name)
                except (ClientError, BotoCoreError) as e:
                    flash(f"Upload ke S3 gagal: {e}", "error")
                    return redirect(url_for("laporan"))
            else:
                flash("Format file foto tidak didukung.", "error")
                return redirect(url_for("laporan"))

        data = LaporanSampah(
            judul=judul,
            deskripsi=deskripsi,
            lokasi=lokasi,
            foto=file_ref,
            status="Baru",
        )
        db.session.add(data)
        db.session.commit()
        flash("Laporan berhasil ditambahkan.", "success")
        return redirect(url_for("laporan"))

    data_laporan = LaporanSampah.query.order_by(LaporanSampah.created_at.desc()).all()
    return render_template("laporan.html", data_laporan=data_laporan)


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    # filename = local filename OR s3 key
    if USE_S3:
        try:
            url = s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": S3_BUCKET_NAME, "Key": filename},
                ExpiresIn=3600
            )
            return redirect(url)
        except (ClientError, BotoCoreError):
            flash("File tidak dapat diakses dari S3.", "error")
            return redirect(url_for("laporan"))
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

# ... route jadwal & petugas tetap sama ...

def is_production():
    return app.config.get("ENV") == "production"

if __name__ == "__main__":
    init_db()
    debug_mode = not is_production()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=debug_mode)
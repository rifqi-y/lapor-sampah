import os
from datetime import datetime
import time
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# =========================
# ENV / CONFIG
# =========================
# default aman untuk local dev
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "mysql+pymysql://root:@localhost:3306/persampahan_db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["ENV"] = os.getenv("FLASK_ENV", "development")

UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

db = SQLAlchemy(app)


# =========================
# MODEL
# =========================
class LaporanSampah(db.Model):
    __tablename__ = "laporan_sampah"
    id = db.Column(db.Integer, primary_key=True)
    judul = db.Column(db.String(120), nullable=False)
    deskripsi = db.Column(db.Text, nullable=False)
    lokasi = db.Column(db.String(255), nullable=False)
    foto = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(30), default="baru")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class JadwalAngkut(db.Model):
    __tablename__ = "jadwal_angkut"
    id = db.Column(db.Integer, primary_key=True)
    wilayah = db.Column(db.String(120), nullable=False)
    tanggal = db.Column(db.Date, nullable=False)
    jam = db.Column(db.String(20), nullable=False)
    keterangan = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(30), default="terjadwal")


class Petugas(db.Model):
    __tablename__ = "petugas"
    id = db.Column(db.Integer, primary_key=True)
    nama = db.Column(db.String(120), nullable=False)
    area_tugas = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(30), default="siaga")
    update_terakhir = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


JADWAL_STATUS_OPTIONS = {"terjadwal", "berjalan", "selesai"}


# =========================
# HELPER
# =========================
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# =========================
# ROUTES
# =========================
@app.route("/")
def index():
    total_laporan = LaporanSampah.query.count()
    total_jadwal = JadwalAngkut.query.count()
    total_petugas = Petugas.query.count()

    laporan_baru = LaporanSampah.query.filter_by(status="baru").count()
    jadwal_hari_ini = JadwalAngkut.query.filter_by(tanggal=datetime.utcnow().date()).count()
    petugas_aktif = Petugas.query.filter(Petugas.status.in_(["bertugas", "siaga"])).count()

    return render_template(
        "index.html",
        total_laporan=total_laporan,
        total_jadwal=total_jadwal,
        total_petugas=total_petugas,
        laporan_baru=laporan_baru,
        jadwal_hari_ini=jadwal_hari_ini,
        petugas_aktif=petugas_aktif,
    )


# ====== FITUR 1: Laporan Sampah Liar ======
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

        filename = None
        if foto_file and foto_file.filename:
            if allowed_file(foto_file.filename):
                safe_name = secure_filename(foto_file.filename)
                # kasih prefix timestamp supaya tidak bentrok
                filename = f"{int(time.time())}_{safe_name}"
                foto_file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            else:
                flash("Format file foto tidak didukung.", "error")
                return redirect(url_for("laporan"))

        data = LaporanSampah(
            judul=judul,
            deskripsi=deskripsi,
            lokasi=lokasi,
            foto=filename,
            status="baru",
        )
        db.session.add(data)
        db.session.commit()
        flash("Laporan berhasil ditambahkan.", "success")
        return redirect(url_for("laporan"))

    data_laporan = LaporanSampah.query.order_by(LaporanSampah.created_at.desc()).all()
    return render_template("laporan.html", data_laporan=data_laporan)


@app.route("/laporan/<int:laporan_id>/status", methods=["POST"])
def update_status_laporan(laporan_id):
    laporan_data = LaporanSampah.query.get_or_404(laporan_id)
    status_baru = request.form.get("status")
    if status_baru in ["baru", "diproses", "selesai"]:
        laporan_data.status = status_baru
        db.session.commit()
        flash("Status laporan diperbarui.", "success")
    else:
        flash("Status tidak valid.", "error")
    return redirect(url_for("laporan"))


# ====== FITUR 2: Jadwal Pengangkutan ======
@app.route("/jadwal", methods=["GET", "POST"])
def jadwal():
    if request.method == "POST":
        wilayah = request.form.get("wilayah")
        tanggal = request.form.get("tanggal")
        jam = request.form.get("jam")
        keterangan = request.form.get("keterangan")
        status = request.form.get("status", "terjadwal")

        if status not in JADWAL_STATUS_OPTIONS:
            flash("Status jadwal tidak valid.", "error")
            return redirect(url_for("jadwal"))

        if not wilayah or not tanggal or not jam:
            flash("Wilayah, tanggal, dan jam wajib diisi.", "error")
            return redirect(url_for("jadwal"))

        try:
            tanggal_obj = datetime.strptime(tanggal, "%Y-%m-%d").date()
        except ValueError:
            flash("Format tanggal tidak valid.", "error")
            return redirect(url_for("jadwal"))

        item = JadwalAngkut(
            wilayah=wilayah,
            tanggal=tanggal_obj,
            jam=jam,
            keterangan=keterangan,
            status=status
        )
        db.session.add(item)
        db.session.commit()
        flash("Jadwal berhasil ditambahkan.", "success")
        return redirect(url_for("jadwal"))

    data_jadwal = JadwalAngkut.query.order_by(JadwalAngkut.tanggal.asc()).all()
    return render_template("jadwal.html", data_jadwal=data_jadwal)


@app.route("/jadwal/<int:jadwal_id>/status", methods=["POST"])
def update_status_jadwal(jadwal_id):
    item = JadwalAngkut.query.get_or_404(jadwal_id)
    status_baru = request.form.get("status")

    if status_baru in JADWAL_STATUS_OPTIONS:
        item.status = status_baru
        db.session.commit()
        flash("Status jadwal diperbarui.", "success")
    else:
        flash("Status tidak valid.", "error")

    return redirect(url_for("jadwal"))


@app.route("/jadwal/<int:jadwal_id>/hapus", methods=["POST"])
def hapus_jadwal(jadwal_id):
    item = JadwalAngkut.query.get_or_404(jadwal_id)
    db.session.delete(item)
    db.session.commit()
    flash("Jadwal dihapus.", "success")
    return redirect(url_for("jadwal"))


# ====== FITUR 3: Monitoring Petugas ======
@app.route("/petugas", methods=["GET", "POST"])
def petugas():
    if request.method == "POST":
        nama = request.form.get("nama")
        area_tugas = request.form.get("area_tugas")
        status = request.form.get("status", "siaga")

        if not nama or not area_tugas:
            flash("Nama dan area tugas wajib diisi.", "error")
            return redirect(url_for("petugas"))

        item = Petugas(
            nama=nama,
            area_tugas=area_tugas,
            status=status
        )
        db.session.add(item)
        db.session.commit()
        flash("Data petugas ditambahkan.", "success")
        return redirect(url_for("petugas"))

    data_petugas = Petugas.query.order_by(Petugas.update_terakhir.desc()).all()
    return render_template("petugas.html", data_petugas=data_petugas)


@app.route("/petugas/<int:petugas_id>/status", methods=["POST"])
def update_status_petugas(petugas_id):
    item = Petugas.query.get_or_404(petugas_id)
    status_baru = request.form.get("status")
    if status_baru in ["siaga", "bertugas", "istirahat", "selesai"]:
        item.status = status_baru
        item.update_terakhir = datetime.utcnow()
        db.session.commit()
        flash("Status petugas diperbarui.", "success")
    else:
        flash("Status tidak valid.", "error")
    return redirect(url_for("petugas"))


@app.route("/petugas/<int:petugas_id>/hapus", methods=["POST"])
def hapus_petugas(petugas_id):
    item = Petugas.query.get_or_404(petugas_id)
    db.session.delete(item)
    db.session.commit()
    flash("Data petugas dihapus.", "success")
    return redirect(url_for("petugas"))


# Serve uploaded files sederhana (local only)
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    from flask import send_from_directory
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

def is_production():
    return app.config.get("ENV") == "production"

if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    # debug aktif hanya saat development
    debug_mode = not is_production()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=debug_mode)
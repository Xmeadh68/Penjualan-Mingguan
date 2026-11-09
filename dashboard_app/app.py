# -*- coding: utf-8 -*-
"""
DASHBOARD KLASTER PENJUALAN MINGGUAN (JARAK DTW)
================================================
Membaca 7 berkas hasil skrip analisis (folder `dashboard_output`):
  ringkasan.json, produk_klaster.csv, profil_klaster.csv, kurva_klaster.csv,
  deret_produk.csv, perbandingan_metode.csv, validasi_parameter.csv

Jalankan:   streamlit run app.py
Lokasi data (urutan pencarian): variabel lingkungan DASHBOARD_DATA_DIR -> ./dashboard_output
-> ./data -> folder yang sama dengan app.py -> unggah ZIP lewat sidebar.
"""
import inspect
import io
import json
import os
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

st.set_page_config(page_title="Dashboard Klaster Penjualan", page_icon="📊", layout="wide",
                   initial_sidebar_state="collapsed")

# =====================================================================
# TAMPILAN (CSS)
# =====================================================================
st.markdown("""
<style>
.block-container {padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1280px;}
.hero {background: linear-gradient(120deg, #264653 0%, #2a9d8f 60%, #52b69a 100%);
       border-radius: 22px; padding: 28px 34px; color: #fff; margin-bottom: 18px;
       box-shadow: 0 8px 24px rgba(38,70,83,.25);}
.hero-title {font-size: 1.95rem; font-weight: 800; line-height: 1.2; margin-bottom: 4px;}
.hero-sub {font-size: 1.02rem; opacity: .92; margin-bottom: 14px;}
.chip {display: inline-block; background: rgba(255,255,255,.18); border: 1px solid rgba(255,255,255,.28);
       padding: 4px 12px; border-radius: 999px; font-size: .8rem; margin: 0 8px 6px 0;}
.kpi {border-radius: 16px; padding: 16px 18px; background: rgba(128,128,128,.08);
      border: 1px solid rgba(128,128,128,.18); height: 100%;}
.kpi .l {font-size: .72rem; letter-spacing: .06em; text-transform: uppercase; opacity: .68; font-weight: 600;}
.kpi .v {font-size: 2rem; font-weight: 800; line-height: 1.15; margin-top: 2px;}
.kpi .s {font-size: .8rem; opacity: .72; margin-top: 2px;}
.card {border-radius: 16px; padding: 16px 20px; background: rgba(128,128,128,.07);
       border: 1px solid rgba(128,128,128,.16); margin-bottom: 10px;}
.card h4 {margin: 0 0 6px 0; font-size: 1.02rem;}
.card .row {display: flex; justify-content: space-between; font-size: .88rem; padding: 3px 0;
            border-bottom: 1px dashed rgba(128,128,128,.22);}
.card .row:last-child {border-bottom: none;}
.card .row span:first-child {opacity: .7;}
.callout {border-radius: 12px; padding: 12px 16px; margin: 8px 0; font-size: .92rem; line-height: 1.45;}
.callout.warn {background: rgba(233,196,106,.18); border-left: 5px solid #e9c46a;}
.callout.info {background: rgba(42,157,143,.12); border-left: 5px solid #2a9d8f;}
.pill {display: inline-block; padding: 3px 12px; border-radius: 999px; font-size: .78rem; font-weight: 700; color: #fff;}
.sec {font-size: 1.2rem; font-weight: 700; margin: 22px 0 4px 0;}
.sec-sub {font-size: .88rem; opacity: .7; margin-bottom: 8px;}
.stTabs [data-baseweb="tab-list"] {gap: 8px;}
.stTabs [data-baseweb="tab"] {border-radius: 12px 12px 0 0; padding: 10px 20px; font-weight: 600;}
</style>
""", unsafe_allow_html=True)

PAL = ["#2a9d8f", "#e76f51", "#3d5a80", "#e9c46a", "#8ab17d", "#9b5de5", "#f4a261", "#577590"]
NOISE_C, JARANG_C = "#b8c0cc", "#f2cc8f"


# =====================================================================
# UTILITAS
# =====================================================================
def _stretch_kw(fn):
    """Lebar penuh lintas versi Streamlit: versi baru sudah default 'stretch', versi lama memakai use_container_width."""
    ps = inspect.signature(fn).parameters
    if "width" in ps and ps["width"].default == "stretch":
        return {}
    return {"use_container_width": True} if "use_container_width" in ps else {}


PLOT_KW, DF_KW = _stretch_kw(st.plotly_chart), _stretch_kw(st.dataframe)


def show(fig, key):
    st.plotly_chart(fig, key=key, **PLOT_KW)


def show_df(df, **kw):
    st.dataframe(df, hide_index=True, **DF_KW, **kw)


def fmt(x, d=2):
    return "-" if pd.isna(x) else f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def rgba(hex_c, a):
    h = hex_c.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{a})"


def code_key(c):
    return int(re.sub(r"\D", "", str(c)) or 0)


def sil_info(s):
    """Tafsiran silhouette (Kaufman & Rousseeuw) -> (label, warna)."""
    if s > 0.70:
        return "Kuat", "#2a9d8f"
    if s > 0.50:
        return "Masuk akal", "#8ab17d"
    if s > 0.25:
        return "Lemah", "#e9a23b"
    return "Hampir tidak ada struktur", "#e76f51"


def kpi(col, label, value, sub="", color="#2a9d8f"):
    col.markdown(f"""<div class="kpi" style="border-left:6px solid {color}">
        <div class="l">{label}</div><div class="v">{value}</div><div class="s">{sub}</div></div>""",
                 unsafe_allow_html=True)


def callout(text, kind="info"):
    st.markdown(f'<div class="callout {kind}">{text}</div>', unsafe_allow_html=True)


def section(title, sub=""):
    st.markdown(f'<div class="sec">{title}</div><div class="sec-sub">{sub}</div>', unsafe_allow_html=True)


# =====================================================================
# MEMUAT DATA
# =====================================================================
FILES = ["ringkasan.json", "produk_klaster.csv", "profil_klaster.csv", "kurva_klaster.csv",
         "deret_produk.csv", "perbandingan_metode.csv", "validasi_parameter.csv"]


def find_dir():
    here = Path(__file__).parent
    cands = [os.environ.get("DASHBOARD_DATA_DIR"), here / "dashboard_output", here / "data", here, Path("dashboard_output")]
    for c in cands:
        if c and (Path(c) / "ringkasan.json").exists():
            return str(c)
    return None


@st.cache_data(show_spinner="Memuat data...")
def load_data(dir_path, zip_bytes):
    if zip_bytes is not None:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        names = {Path(n).name: n for n in zf.namelist()}
        missing = [f for f in FILES if f not in names]
        read_bytes = lambda f: zf.read(names[f])
    else:
        missing = [f for f in FILES if not (Path(dir_path) / f).exists()]
        read_bytes = lambda f: (Path(dir_path) / f).read_bytes()
    if missing:
        raise FileNotFoundError("Berkas tidak ditemukan: " + ", ".join(missing))
    csv = lambda f, **kw: pd.read_csv(io.BytesIO(read_bytes(f)), **kw)
    ring = json.loads(read_bytes("ringkasan.json").decode("utf-8"))
    produk = csv("produk_klaster.csv", dtype={"Product_Code": str, "klaster": str})
    profil = csv("profil_klaster.csv", dtype={"klaster": str})
    kurva = csv("kurva_klaster.csv", dtype={"klaster": str})
    deret = csv("deret_produk.csv", dtype={"Product_Code": str})
    cmp_ = csv("perbandingan_metode.csv")
    vp = csv("validasi_parameter.csv")
    unit_w = deret.pivot(index="Product_Code", columns="minggu", values="unit")
    norm_w = deret.pivot(index="Product_Code", columns="minggu", values="normalisasi")
    produk["produk_wakil"] = produk["produk_wakil"].astype(str).str.lower().eq("true")
    return dict(ring=ring, produk=produk, profil=profil, kurva=kurva, unit_w=unit_w, norm_w=norm_w, cmp=cmp_, vp=vp)


with st.sidebar:
    st.markdown("### 📊 Dashboard Klaster")
    up = st.file_uploader("Ganti data: unggah dashboard_output.zip", type="zip")
    st.caption("Kosongkan untuk memakai folder `dashboard_output` di samping app.py.")

dir_path = find_dir()
zip_bytes = up.getvalue() if up is not None else None
if dir_path is None and zip_bytes is None:
    st.error("Data belum ditemukan.")
    st.markdown("Taruh folder **`dashboard_output`** (hasil skrip analisis) di samping `app.py`, "
                "atau unggah **`dashboard_output.zip`** lewat sidebar di kiri.")
    st.stop()
try:
    DATA = load_data(dir_path, zip_bytes)
except Exception as e:
    st.error(f"Gagal memuat data: {e}")
    st.stop()

ring, produk, profil, kurva = DATA["ring"], DATA["produk"], DATA["profil"], DATA["kurva"]
unit_w, norm_w, cmp_, vp = DATA["unit_w"], DATA["norm_w"], DATA["cmp"], DATA["vp"]

clusters = sorted([k for k in produk["klaster"].unique() if k.isdigit()], key=int)
has_noise = (produk["klaster"] == "noise").any()
has_prob = bool(produk["probabilitas"].notna().any())
seg_order = clusters + (["noise"] if has_noise else [])
nama_seg = produk.drop_duplicates("klaster").set_index("klaster")["nama_klaster"].to_dict()


def color_of(seg):
    if seg == "noise":
        return NOISE_C
    if seg == "jarang":
        return JARANG_C
    return PAL[clusters.index(seg) % len(PAL)] if seg in clusters else "#999999"


def label_of(seg):
    return {"noise": "Noise", "jarang": "Produk jarang"}.get(seg, f"Klaster {seg}")


metode = ring["metode_terpilih"]
sil = float(ring["silhouette"])
sil_lab, sil_col = sil_info(sil)
n_total, n_reg, n_jar = ring["jumlah_produk_total"], ring["jumlah_produk_reguler"], ring["jumlah_produk_jarang"]

# =====================================================================
# HERO
# =====================================================================
chips = "".join(f'<span class="chip">{t}</span>' for t in [
    f"Metode: {metode}", f"Jarak: {ring['jarak']}", f"Sumber: {ring['sumber_data']}",
    f"Dibuat: {ring['dibuat_pada'][:10]}"])
st.markdown(f"""<div class="hero">
  <div class="hero-title">Pengelompokan Produk Berdasarkan Pola Penjualan Mingguan</div>
  <div class="hero-sub">{n_total} produk · {ring['jumlah_minggu']} minggu · jarak DTW · validasi silhouette</div>
  {chips}</div>""", unsafe_allow_html=True)

tab1, tab2, tab3, tab4 = st.tabs(["📌 Ringkasan", "🧩 Klaster", "🔎 Cari Produk", "✅ Validasi"])

# =====================================================================
# TAB 1: RINGKASAN
# =====================================================================
with tab1:
    c = st.columns(6)
    kpi(c[0], "Total produk", f"{n_total}", "seluruh produk di data", "#264653")
    kpi(c[1], "Produk reguler", f"{n_reg}", "diklasterkan", "#2a9d8f")
    kpi(c[2], "Produk jarang", f"{n_jar}", f"> {int(ring['ambang_produk_jarang_prop_minggu_nol'] * 100)}% minggu bernilai nol", "#e9c46a")
    kpi(c[3], "Klaster", f"{ring['jumlah_klaster']}", f"metode {metode}", "#9b5de5")
    kpi(c[4], "Cakupan", f"{fmt(ring['cakupan_persen'], 1)}%", "produk reguler yang berklaster", "#f4a261")
    kpi(c[5], "Silhouette", fmt(sil, 3), sil_lab, sil_col)

    st.write("")
    left, mid, right = st.columns([1.15, 1, 1.1])
    with left:
        section("Komposisi produk", "Seluruh produk menurut segmen")
        segs = seg_order + ["jarang"]
        cnt = produk["klaster"].value_counts()
        fig = go.Figure(go.Pie(
            labels=[f"{label_of(s)}" for s in segs], values=[int(cnt.get(s, 0)) for s in segs], hole=.62, sort=False,
            marker=dict(colors=[color_of(s) for s in segs], line=dict(color="rgba(0,0,0,0)", width=0)),
            textinfo="percent", hovertemplate="%{label}: %{value} produk (%{percent})<extra></extra>"))
        fig.update_layout(height=340, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=-0.05),
                          annotations=[dict(text=f"<b>{n_total}</b><br>produk", x=.5, y=.5, showarrow=False, font=dict(size=18))])
        show(fig, "donut")
    with mid:
        section("Kekuatan struktur klaster", "Silhouette (Kaufman & Rousseeuw)")
        fig = go.Figure(go.Indicator(
            mode="gauge+number", value=sil, number=dict(valueformat=".3f"),
            gauge=dict(axis=dict(range=[-0.2, 1]), bar=dict(color="#264653", thickness=.28),
                       steps=[dict(range=[-0.2, 0.25], color="#f4b8a8"), dict(range=[0.25, 0.5], color="#f6dfa4"),
                              dict(range=[0.5, 0.7], color="#c5e0b4"), dict(range=[0.7, 1], color="#8fd0c5")])))
        fig.update_layout(height=300, margin=dict(l=20, r=20, t=30, b=0))
        show(fig, "gauge")
        st.markdown(f'<div style="text-align:center"><span class="pill" style="background:{sil_col}">{sil_lab}</span></div>',
                    unsafe_allow_html=True)
    with right:
        section("Temuan utama", "Dihitung otomatis dari hasil analisis")
        pr = profil.set_index("klaster")
        for s in clusters:
            r = pr.loc[s]
            st.markdown(f"""<div class="card" style="border-left:6px solid {color_of(s)}">
              <h4>Klaster {s} · {r['nama_klaster']}</h4>
              <div class="row"><span>Jumlah produk</span><b>{int(r['jumlah_produk'])}</b></div>
              <div class="row"><span>Rata-rata penjualan</span><b>{fmt(r['rata2_penjualan_per_minggu'], 1)} unit/minggu</b></div>
              <div class="row"><span>Variabilitas (CV)</span><b>{fmt(r['CV_rata2'])}</b></div></div>""", unsafe_allow_html=True)
        if has_noise and clusters:
            ac_c = pr.loc[clusters, "autokorelasi_lag1"].astype(float)
            ac_n = float(pr.loc["noise", "autokorelasi_lag1"])
            if ac_c.min() > ac_n:
                callout(f"Produk di klaster memiliki ketergantungan antar-minggu yang lebih kuat "
                        f"(autokorelasi lag-1 {fmt(ac_c.min())}–{fmt(ac_c.max())}) dibanding noise ({fmt(ac_n)}).", "info")

    for t in ring.get("catatan", []):
        callout(f"⚠️ <b>Catatan:</b> {t}", "warn")
    with st.expander("📖 Cara membaca hasil ini"):
        st.markdown(f"""
- **Produk jarang**: produk dengan lebih dari {int(ring['ambang_produk_jarang_prop_minggu_nol'] * 100)}% minggu bernilai nol. Polanya didominasi minggu kosong sehingga dikelompokkan terpisah.
- **Klaster**: kelompok produk reguler dengan *bentuk* pola penjualan yang mirip (volume tidak dibandingkan karena data dinormalisasi).
- **Noise**: produk yang tidak berada di area padat; polanya tidak cukup mirip dengan banyak produk lain. Ini **bukan** produk rusak atau data salah.
- **Cakupan**: persentase produk reguler yang masuk klaster.
- **Silhouette**: seberapa jelas sebuah produk lebih dekat ke klasternya sendiri daripada ke klaster lain (−1 sampai 1; makin tinggi makin baik).
- **Normalisasi**: {ring['normalisasi']}.
""")

# =====================================================================
# TAB 2: KLASTER
# =====================================================================
with tab2:
    section("Pola penjualan per klaster", "Garis tebal = rata-rata klaster; area berwarna = rentang 25%–75% produk")
    cc = st.columns([1.3, 1, 3])
    mode = cc[0].radio("Satuan", ["Ternormalisasi (bentuk pola)", "Unit (penjualan asli)"], horizontal=False)
    show_noise = cc[1].checkbox("Tampilkan noise", value=False, disabled=not has_noise)
    fig = go.Figure()
    for s in seg_order:
        if s == "noise" and not show_noise:
            continue
        d = kurva[kurva["klaster"] == s].sort_values("minggu")
        if d.empty:
            continue
        col = color_of(s)
        if mode.startswith("Ternormalisasi"):
            fig.add_trace(go.Scatter(x=d["minggu"], y=d["p75_norm"], mode="lines", line=dict(width=0),
                                     showlegend=False, hoverinfo="skip"))
            fig.add_trace(go.Scatter(x=d["minggu"], y=d["p25_norm"], mode="lines", line=dict(width=0), fill="tonexty",
                                     fillcolor=rgba(col, .16), showlegend=False, hoverinfo="skip"))
            y = d["rata2_norm"]
        else:
            y = d["rata2_unit"]
        fig.add_trace(go.Scatter(x=d["minggu"], y=y, mode="lines", name=label_of(s), line=dict(color=col, width=3.2)))
    fig.update_layout(height=400, margin=dict(l=0, r=0, t=10, b=0), xaxis_title="Minggu",
                      yaxis_title="Nilai ternormalisasi (0–1)" if mode.startswith("Ternormalisasi") else "Unit per minggu",
                      legend=dict(orientation="h", y=1.1), hovermode="x unified")
    show(fig, "pola")

    section("Peta produk", "Setiap titik = satu produk. Produk yang berdekatan memiliki pola penjualan yang mirip (proyeksi 2D dari jarak DTW).")
    reg = produk[produk["jenis_produk"] == "reguler"].copy()
    pick = st.multiselect("Tampilkan", [label_of(s) for s in seg_order], default=[label_of(s) for s in seg_order])
    fig = go.Figure()
    for s in seg_order:
        if label_of(s) not in pick:
            continue
        d = reg[reg["klaster"] == s]
        fig.add_trace(go.Scatter(
            x=d["peta_x"], y=d["peta_y"], mode="markers", name=label_of(s),
            marker=dict(size=7 if s == "noise" else 11, color=color_of(s), opacity=.55 if s == "noise" else .92,
                        line=dict(width=0 if s == "noise" else 1, color="white")),
            customdata=np.c_[d["Product_Code"], d["nama_klaster"], d["rata2_penjualan"].round(1)],
            hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<br>%{customdata[2]} unit/minggu<extra></extra>"))
    w = reg[reg["produk_wakil"] & reg["klaster"].isin([k for k in seg_order if label_of(k) in pick])]
    if not w.empty:
        fig.add_trace(go.Scatter(x=w["peta_x"], y=w["peta_y"], mode="markers+text", name="Produk wakil",
                                 text=w["Product_Code"], textposition="top center",
                                 marker=dict(symbol="star", size=20, color="#264653", line=dict(width=1.5, color="white")),
                                 hovertemplate="<b>%{text}</b> (produk wakil)<extra></extra>"))
    fig.update_layout(height=520, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=1.07),
                      xaxis=dict(showticklabels=False, zeroline=False, title=""),
                      yaxis=dict(showticklabels=False, zeroline=False, title=""))
    show(fig, "peta")
    st.caption("Jarak pada peta hanya pendekatan 2D dari jarak DTW yang sebenarnya, jadi baca sebagai gambaran umum.")

    section("Profil klaster", "Ringkasan tiap kelompok")
    pshow = profil.copy()
    pshow["klaster"] = pshow["klaster"].map(lambda k: label_of(k))
    show_df(pshow.rename(columns={
        "klaster": "Klaster", "nama_klaster": "Nama", "jumlah_produk": "Jumlah produk",
        "persen_dari_reguler": "% dari reguler", "produk_wakil": "Produk wakil",
        "rata2_penjualan_per_minggu": "Rata-rata unit/minggu", "CV_rata2": "CV",
        "autokorelasi_lag1": "Autokorelasi lag-1", "silhouette_klaster": "Silhouette"}).round(3))

    if clusters:
        section("Anggota klaster", "Daftar produk dalam klaster terpilih")
        cc = st.columns([1, 3])
        sel = cc[0].selectbox("Klaster", clusters, format_func=label_of)
        members = produk[produk["klaster"] == sel].copy()
        sort_col = "probabilitas" if has_prob else "silhouette_produk"
        members = members.sort_values(sort_col, ascending=False)
        cols = ["Product_Code", "produk_wakil", "rata2_penjualan", "CV"] + (["probabilitas"] if has_prob else []) + ["silhouette_produk"]
        cfg = {"Product_Code": "Kode", "produk_wakil": st.column_config.CheckboxColumn("Wakil"),
               "rata2_penjualan": st.column_config.NumberColumn("Unit/minggu", format="%.1f"),
               "CV": st.column_config.NumberColumn("CV", format="%.2f"),
               "silhouette_produk": st.column_config.NumberColumn("Silhouette", format="%.3f")}
        if has_prob:
            cfg["probabilitas"] = st.column_config.ProgressColumn("Probabilitas", min_value=0, max_value=1, format="%.2f")
        show_df(members[cols], column_config=cfg)

# =====================================================================
# TAB 3: CARI PRODUK
# =====================================================================
with tab3:
    section("Cari produk", "Pilih atau ketik kode produk untuk melihat posisinya")
    codes_sorted = sorted(produk["Product_Code"].tolist(), key=code_key)
    cs = st.columns([1, 2])
    code = cs[0].selectbox("Kode produk", codes_sorted, index=0)
    mode3 = cs[1].radio("Tampilkan kurva dalam", ["Unit (penjualan asli)", "Ternormalisasi (bentuk pola)"], horizontal=True)
    row = produk[produk["Product_Code"] == code].iloc[0]
    seg = row["klaster"]
    col_seg = color_of(seg)

    a, b = st.columns([1, 2.2])
    with a:
        st.markdown(f"""<div class="card" style="border-left:6px solid {col_seg}">
          <h4>{code} <span class="pill" style="background:{col_seg};margin-left:6px">{label_of(seg)}</span></h4>
          <div class="row"><span>Jenis</span><b>{row['jenis_produk']}</b></div>
          <div class="row"><span>Segmen</span><b>{row['nama_klaster']}</b></div>
          <div class="row"><span>Rata-rata penjualan</span><b>{fmt(row['rata2_penjualan'], 1)} unit/minggu</b></div>
          <div class="row"><span>Variabilitas (CV)</span><b>{fmt(row['CV'])}</b></div>
          <div class="row"><span>Minggu bernilai nol</span><b>{fmt(row['prop_minggu_nol'] * 100, 0)}%</b></div>
          <div class="row"><span>Probabilitas klaster</span><b>{fmt(row['probabilitas'])}</b></div>
          <div class="row"><span>Silhouette produk</span><b>{fmt(row['silhouette_produk'], 3)}</b></div>
          <div class="row"><span>Produk wakil klaster</span><b>{'Ya ⭐' if row['produk_wakil'] else 'Bukan'}</b></div>
        </div>""", unsafe_allow_html=True)
        if seg == "noise":
            callout("Produk ini <b>noise</b>: polanya tidak cukup mirip dengan banyak produk lain, sehingga tidak masuk klaster mana pun.", "info")
        elif seg == "jarang":
            callout("Produk ini <b>jarang</b>: banyak minggu bernilai nol sehingga tidak diklasterkan.", "info")
        elif pd.notna(row["silhouette_produk"]) and row["silhouette_produk"] < 0:
            callout("Silhouette negatif: produk ini lebih mirip klaster lain (produk batas).", "warn")
    with b:
        xs = list(unit_w.columns)
        use_norm = mode3.startswith("Ternormalisasi")
        ys = (norm_w if use_norm else unit_w).loc[code].values
        fig = go.Figure()
        kd = kurva[kurva["klaster"] == seg].sort_values("minggu")
        if not kd.empty:
            if use_norm:
                fig.add_trace(go.Scatter(x=kd["minggu"], y=kd["p75_norm"], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
                fig.add_trace(go.Scatter(x=kd["minggu"], y=kd["p25_norm"], mode="lines", line=dict(width=0), fill="tonexty",
                                         fillcolor=rgba(col_seg, .18), name="Rentang 25–75% klaster", hoverinfo="skip"))
            fig.add_trace(go.Scatter(x=kd["minggu"], y=kd["rata2_norm" if use_norm else "rata2_unit"], mode="lines",
                                     name=f"Rata-rata {label_of(seg)}", line=dict(color=col_seg, width=2.5, dash="dash")))
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers", name=code, line=dict(color="#264653", width=3),
                                 marker=dict(size=6)))
        fig.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0), xaxis_title="Minggu",
                          yaxis_title="Nilai ternormalisasi (0–1)" if use_norm else "Unit per minggu",
                          legend=dict(orientation="h", y=1.12), hovermode="x unified")
        show(fig, "produk_kurva")

    m1, m2 = st.columns([1.1, 1])
    with m1:
        section("Posisi di peta produk", "Bintang = produk terpilih")
        regp = produk[produk["jenis_produk"] == "reguler"]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=regp["peta_x"], y=regp["peta_y"], mode="markers", showlegend=False, hoverinfo="skip",
                                 marker=dict(size=6, color=[color_of(k) for k in regp["klaster"]], opacity=.55)))
        if pd.notna(row["peta_x"]):
            fig.add_trace(go.Scatter(x=[row["peta_x"]], y=[row["peta_y"]], mode="markers+text", text=[code], textposition="top center",
                                     showlegend=False, marker=dict(symbol="star", size=24, color="#264653", line=dict(width=2, color="white"))))
        fig.update_layout(height=340, margin=dict(l=0, r=0, t=10, b=0), xaxis=dict(visible=False), yaxis=dict(visible=False))
        show(fig, "produk_peta")
        if pd.isna(row["peta_x"]):
            st.caption("Produk jarang tidak ikut dipetakan.")
    with m2:
        if seg in clusters:
            section("Produk sekelompok", "Anggota klaster yang sama")
            sk = "probabilitas" if has_prob else "silhouette_produk"
            mates = produk[(produk["klaster"] == seg) & (produk["Product_Code"] != code)].sort_values(sk, ascending=False).head(10)
            show_df(mates[["Product_Code", "rata2_penjualan", "CV", sk]].rename(columns={
                "Product_Code": "Kode", "rata2_penjualan": "Unit/minggu", "CV": "CV", sk: sk.replace("_", " ").capitalize()}).round(2))

    section("Telusuri semua produk", "Filter lalu unduh sebagai CSV")
    f1, f2, f3 = st.columns(3)
    seg_opts = seg_order + ["jarang"]
    fseg = f1.multiselect("Segmen", seg_opts, default=seg_opts, format_func=label_of)
    vmin, vmax = float(produk["rata2_penjualan"].min()), float(produk["rata2_penjualan"].max())
    vrange = f2.slider("Rata-rata unit/minggu", vmin, vmax, (vmin, vmax))
    qtext = f3.text_input("Cari kode (mis. P12)")
    tbl = produk[produk["klaster"].isin(fseg) & produk["rata2_penjualan"].between(*vrange)]
    if qtext:
        tbl = tbl[tbl["Product_Code"].str.contains(qtext, case=False)]
    tbl = tbl.assign(klaster=tbl["klaster"].map(label_of)).sort_values("Product_Code", key=lambda s: s.map(code_key))
    cols = ["Product_Code", "klaster", "nama_klaster", "rata2_penjualan", "CV", "prop_minggu_nol"] + (["probabilitas"] if has_prob else []) + ["silhouette_produk"]
    cfg = {"Product_Code": "Kode", "klaster": "Segmen", "nama_klaster": "Nama",
           "rata2_penjualan": st.column_config.NumberColumn("Unit/minggu", format="%.1f"),
           "CV": st.column_config.NumberColumn("CV", format="%.2f"),
           "prop_minggu_nol": st.column_config.NumberColumn("Minggu nol", format="%.2f"),
           "silhouette_produk": st.column_config.NumberColumn("Silhouette", format="%.3f")}
    if has_prob:
        cfg["probabilitas"] = st.column_config.ProgressColumn("Probabilitas", min_value=0, max_value=1, format="%.2f")
    show_df(tbl[cols], column_config=cfg)
    st.caption(f"{len(tbl)} produk ditampilkan")
    st.download_button("⬇️ Unduh tabel (CSV)", tbl[cols].to_csv(index=False).encode("utf-8"),
                       "produk_terfilter.csv", "text/csv")

# =====================================================================
# TAB 4: VALIDASI
# =====================================================================
with tab4:
    section("Perbandingan metode", "Ukuran validasi: silhouette (dihitung pada produk yang berklaster). Metode terpilih ditandai hijau.")
    cm = cmp_.copy()
    cm["cakupan_pct"] = cm["cakupan_produk"] * 100
    cols_ = ["#2a9d8f" if t else "#b8c0cc" for t in cm["terpilih"]]
    fig = make_subplots(rows=1, cols=2, subplot_titles=("Silhouette (makin tinggi makin baik)", "Cakupan produk (%)"), horizontal_spacing=.12)
    fig.add_trace(go.Bar(x=cm["metode"], y=cm["silhouette"].fillna(0), marker_color=cols_,
                         text=[fmt(v, 3) for v in cm["silhouette"]], textposition="outside"), row=1, col=1)
    fig.add_trace(go.Bar(x=cm["metode"], y=cm["cakupan_pct"], marker_color=cols_,
                         text=[f"{v:.0f}%" for v in cm["cakupan_pct"]], textposition="outside"), row=1, col=2)
    fig.update_yaxes(range=[0, max(0.4, cm["silhouette"].max() * 1.3)], row=1, col=1)
    fig.update_yaxes(range=[0, 115], row=1, col=2)
    fig.update_layout(height=380, showlegend=False, margin=dict(l=0, r=0, t=40, b=0))
    show(fig, "cmp")
    callout("Silhouette metode berbasis kepadatan (DBSCAN/HDBSCAN) dihitung <b>hanya pada produk berklaster</b> (noise dibuang), "
            "sedangkan Average Linkage dan PAM memasukkan 100% produk. Karena itu angkanya <b>tidak setara langsung</b>; "
            "baca selalu bersama cakupan.", "warn")
    tshow = cmp_.copy()
    tshow["cakupan_produk"] = (tshow["cakupan_produk"] * 100).round(1)
    show_df(tshow.rename(columns={"metode": "Metode", "parameter": "Parameter", "n_klaster": "Klaster",
                                  "cakupan_produk": "Cakupan (%)", "noise_%": "Noise (%)", "silhouette": "Silhouette",
                                  "memenuhi_syarat": "Memenuhi syarat", "terpilih": "Terpilih"}))
    if (cmp_["memenuhi_syarat"] == "Tidak").any():
        names = ", ".join(cmp_.loc[cmp_["memenuhi_syarat"] == "Tidak", "metode"])
        st.caption(f"Tidak memenuhi syarat (dikeluarkan dari pemilihan): {names}. Syarat: minimal 2 klaster, tiap klaster minimal 5 produk, cakupan minimal 10%.")

    section("Sensitivitas parameter", "Seberapa besar hasil berubah bila parameter digeser")
    s1, s2 = st.columns(2)
    with s1:
        fig = go.Figure()
        for m_, c_ in [("PAM", "#e76f51"), ("Average Linkage", "#3d5a80")]:
            d = vp[vp["metode"] == m_]
            fig.add_trace(go.Scatter(x=d["nilai"], y=d["silhouette"], mode="lines+markers", name=m_, line=dict(color=c_, width=3)))
        fig.update_layout(height=340, margin=dict(l=0, r=0, t=30, b=0), title="Silhouette vs jumlah klaster (k)",
                          xaxis_title="k", yaxis_title="silhouette", legend=dict(orientation="h", y=-0.2))
        show(fig, "sens_k")
    with s2:
        d = vp[vp["metode"] == "HDBSCAN"]
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Scatter(x=d["nilai"], y=d["silhouette"], mode="lines+markers", name="Silhouette",
                                 line=dict(color="#2a9d8f", width=3)), secondary_y=False)
        fig.add_trace(go.Scatter(x=d["nilai"], y=d["cakupan_produk"] * 100, mode="lines+markers", name="Cakupan (%)",
                                 line=dict(color="#f4a261", width=3, dash="dot")), secondary_y=True)
        fig.update_layout(height=340, margin=dict(l=0, r=0, t=30, b=0), title="HDBSCAN: min_cluster_size",
                          xaxis_title="min_cluster_size", legend=dict(orientation="h", y=-0.2))
        fig.update_yaxes(title_text="silhouette", secondary_y=False)
        fig.update_yaxes(title_text="cakupan (%)", secondary_y=True)
        show(fig, "sens_h")
    st.caption("Titik tanpa garis berarti pengaturan tersebut tidak menghasilkan klaster (semua produk menjadi noise).")

    section("Panduan membaca silhouette", "Kaufman & Rousseeuw")
    g = st.columns(4)
    for col, (rng_, lab_, c_) in zip(g, [("> 0,70", "Struktur kuat", "#2a9d8f"), ("0,51 – 0,70", "Masuk akal", "#8ab17d"),
                                          ("0,26 – 0,50", "Lemah", "#e9a23b"), ("≤ 0,25", "Hampir tidak ada struktur", "#e76f51")]):
        kpi(col, lab_, rng_, "", c_)
    st.write("")
    callout(f"Hasil saat ini: silhouette <b>{fmt(sil, 3)}</b> → <b>{sil_lab.lower()}</b>. "
            "Klaster berguna sebagai gambaran kelompok produk, tetapi bukan pemisahan yang tegas.", "info")

st.markdown("---")
st.caption(f"Normalisasi: {ring['normalisasi']} · Validasi: {ring['ukuran_validasi']} · Dibuat {ring['dibuat_pada']}")

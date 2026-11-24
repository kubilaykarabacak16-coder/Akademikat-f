"""
Akademik Referans Bulucu - Flask Uygulaması
Kullanım: python app.py
"""
from flask import Flask, render_template, request, jsonify
from openalex_client import OpenAlexClient, one_year_ago

# ============================================================
# ⚙️  AYARLAR — Buraya kendi e-posta adresinizi yazın
# ============================================================
MAILTO = "ornek@gmail.com"   # <-- DEĞİŞTİRİN
# ============================================================

app = Flask(__name__)
client = OpenAlexClient(mailto=MAILTO)
_institutions_cache: dict = {}


# ------------------------------------------------------------------ #
#  SAYFALAR                                                            #
# ------------------------------------------------------------------ #
@app.route("/")
def index():
    return render_template("index.html")


# ------------------------------------------------------------------ #
#  API: Kurumlar (ülkeye göre)                                        #
# ------------------------------------------------------------------ #
@app.route("/api/institutions")
def api_institutions():
    country = request.args.get("country", "").strip().upper()
    if not country:
        return jsonify({"error": "Ülke kodu gerekli"}), 400

    if country not in _institutions_cache:
        try:
            institutions = client.get_institutions_by_country(country)
            _institutions_cache[country] = institutions
        except Exception as exc:
            return jsonify({"error": f"Kurum listesi alınamadı: {str(exc)}"}), 502

    return jsonify({"institutions": _institutions_cache[country]})


# ------------------------------------------------------------------ #
#  API: Yazar Arama                                                    #
# ------------------------------------------------------------------ #
@app.route("/api/search")
def api_search():
    name = request.args.get("name", "").strip()
    institution_id = request.args.get("institution_id", "").strip()
    country = request.args.get("country", "").strip()

    if not name:
        return jsonify({"error": "Akademisyen adı boş olamaz."}), 400

    try:
        authors = client.search_authors(name, institution_id=institution_id, country=country)
        return jsonify({"authors": authors, "count": len(authors)})
    except Exception as exc:
        return jsonify({"error": f"OpenAlex erişim hatası: {str(exc)}"}), 502


# ------------------------------------------------------------------ #
#  API: Referans Getir                                                 #
# ------------------------------------------------------------------ #
@app.route("/api/references")
def api_references():
    author_id = request.args.get("author_id", "").strip()
    if not author_id:
        return jsonify({"error": "Yazar ID gerekli."}), 400

    from_date = one_year_ago()

    try:
        # 1) Son 1 yıldaki eserleri çek
        works = client.get_author_works(author_id, from_date=from_date)

        if not works:
            return jsonify({
                "works": [],
                "references": [],
                "stats": {"total_works": 0, "total_ref_ids": 0, "unique_refs": 0},
                "from_date": from_date,
            })

        # 2) Tüm referenced_works ID'lerini topla
        all_ref_ids = []
        work_summaries = []
        for w in works:
            ref_ids = w.get("referenced_works") or []
            all_ref_ids.extend(ref_ids)

            # Eser özeti
            authors = w.get("authorships") or []
            author_names = [
                a.get("author", {}).get("display_name", "")
                for a in authors[:3]
            ]
            loc = w.get("primary_location") or {}
            src = loc.get("source") or {}
            work_summaries.append({
                "id": (w.get("id") or "").replace("https://openalex.org/", ""),
                "title": w.get("title") or "Başlıksız",
                "year": w.get("publication_year") or "",
                "type": w.get("type") or "",
                "journal": src.get("display_name") or "",
                "doi": w.get("doi") or "",
                "ref_count": len(ref_ids),
                "authors": author_names,
            })

        # 3) Tekrar edenleri kaldır (maks 500 ile sınırla)
        unique_ids = list(set(all_ref_ids))
        total_ref_ids = len(unique_ids)
        capped = unique_ids[:500]  # Çok büyük listelerde kap

        # 4) Referans detaylarını çek
        references = client.get_works_by_ids(capped)

        return jsonify({
            "works": work_summaries,
            "references": references,
            "stats": {
                "total_works": len(works),
                "total_ref_ids": total_ref_ids,
                "unique_refs": len(references),
                "capped": total_ref_ids > 500,
            },
            "from_date": from_date,
        })

    except Exception as exc:
        return jsonify({"error": f"Referans alınamadı: {str(exc)}"}), 502


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

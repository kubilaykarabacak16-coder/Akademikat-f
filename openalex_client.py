"""
OpenAlex API İstemcisi
Akademisyenlerin son 1 yılda kullandığı referansları getirir.
"""
import requests
import time
from datetime import datetime, timedelta


BASE_URL = "https://api.openalex.org"

# Polite pool için e-posta (rate limit artırır)
MAILTO = "your@email.com"


class OpenAlexClient:
    def __init__(self, mailto: str = MAILTO):
        self.base_url = BASE_URL
        self.mailto = mailto
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": f"AkademikReferans/1.0 (mailto:{mailto})"
        })

    def _get(self, endpoint: str, params: dict = None) -> dict:
        if params is None:
            params = {}
        params["mailto"] = self.mailto
        url = f"{self.base_url}/{endpoint}"
        resp = self.session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------ #
    #  YAZAR ARAMA                                                         #
    # ------------------------------------------------------------------ #
    def search_authors(self, name: str, institution_id: str = "", country: str = "") -> list:
        """
        İsme göre yazar arar. Ülke ve kurum filtresi Python tarafında uygulanır.
        (OpenAlex author endpoint'i bazı filtreleri desteklemediği için)
        """
        params = {
            "search": name,
            "per_page": 25,
        }

        data = self._get("authors", params)
        authors = data.get("results", [])

        # --- Client-side filtreleme ---
        if country:
            country_up = country.upper()
            authors = [
                a for a in authors
                if any(
                    (inst.get("country_code") or "").upper() == country_up
                    for inst in (a.get("last_known_institutions") or [])
                )
            ]

        if institution_id:
            clean = institution_id.replace("https://openalex.org/", "")
            authors = [
                a for a in authors
                if any(
                    (inst.get("id") or "").replace("https://openalex.org/", "") == clean
                    for inst in (a.get("last_known_institutions") or [])
                )
            ]

        return [self._format_author(a) for a in authors]

    def get_institutions_by_country(self, country_code: str) -> list:
        """Ülkedeki kurumları works_count'a göre sıralı getirir."""
        params = {
            "filter": f"country_code:{country_code.upper()}",
            "per_page": 200,
            "sort": "works_count:desc",
            "select": "id,display_name,geo,works_count",
        }
        data = self._get("institutions", params)
        institutions = []
        for inst in data.get("results", []):
            geo = inst.get("geo") or {}
            # geo.region = il/eyalet adı (Istanbul, Ankara...)
            # geo.city   = ilçe/semt adı (Büyükçekmece, Tarsus...)
            # Region varsa onu kullan → doğru il adı verir
            city = geo.get("region") or geo.get("city") or "Diğer"
            institutions.append({
                "id": inst.get("id", "").replace("https://openalex.org/", ""),
                "name": inst.get("display_name", ""),
                "city": city,
                "works_count": inst.get("works_count", 0),
            })
        return institutions

    def _format_author(self, raw: dict) -> dict:
        insts = raw.get("last_known_institutions") or []
        inst_names = [i.get("display_name", "") for i in insts if i.get("display_name")]
        country = insts[0].get("country_code", "") if insts else ""
        return {
            "id": raw.get("id", "").replace("https://openalex.org/", ""),
            "name": raw.get("display_name", ""),
            "works_count": raw.get("works_count", 0),
            "cited_by_count": raw.get("cited_by_count", 0),
            "institution": ", ".join(inst_names) if inst_names else "—",
            "country": country,
            "orcid": raw.get("orcid") or "",
        }

    # ------------------------------------------------------------------ #
    #  YAZARIN ESERLERİ                                                    #
    # ------------------------------------------------------------------ #
    def get_author_works(self, author_id: str, from_date: str) -> list:
        """
        Belirtilen tarihten itibaren yazarın eserlerini getirir.
        """
        # ID normalleştir: A123456 formatında olmalı
        aid = author_id if author_id.startswith("A") else f"A{author_id}"

        params = {
            "filter": f"authorships.author.id:{aid},from_publication_date:{from_date}",
            "per_page": 50,
            "select": (
                "id,title,publication_year,publication_date,"
                "referenced_works,type,primary_location,doi,authorships"
            ),
        }

        data = self._get("works", params)
        return data.get("results", [])

    # ------------------------------------------------------------------ #
    #  REFERANS DETAYLARI                                                  #
    # ------------------------------------------------------------------ #
    def get_works_by_ids(self, work_ids: list, chunk_size: int = 50) -> list:
        """
        OpenAlex ID listesi alır, referans detaylarını toplu sorgular.
        """
        if not work_ids:
            return []

        # URL prefix'ini temizle
        clean = [wid.replace("https://openalex.org/", "") for wid in work_ids]

        all_results = []
        for i in range(0, len(clean), chunk_size):
            chunk = clean[i : i + chunk_size]
            ids_filter = "|".join(chunk)
            params = {
                "filter": f"openalex:{ids_filter}",
                "per_page": chunk_size,
                "select": (
                    "id,title,publication_year,authorships,"
                    "primary_location,type,doi,biblio"
                ),
            }
            try:
                data = self._get("works", params)
                all_results.extend(data.get("results", []))
            except Exception as exc:
                print(f"[WARN] Chunk fetch error: {exc}")
            # Polite rate limiting
            time.sleep(0.12)

        return [self._format_reference(w) for w in all_results]

    def _format_reference(self, raw: dict) -> dict:
        authorships = raw.get("authorships") or []
        authors = [
            a.get("author", {}).get("display_name", "")
            for a in authorships[:6]
            if a.get("author", {}).get("display_name")
        ]
        if len(authorships) > 6:
            authors.append("et al.")

        location = raw.get("primary_location") or {}
        source = location.get("source") or {}
        biblio = raw.get("biblio") or {}

        # Sayfa aralığı
        pages = ""
        if biblio.get("first_page"):
            pages = biblio["first_page"]
            if biblio.get("last_page"):
                pages += f"–{biblio['last_page']}"

        return {
            "id": raw.get("id", "").replace("https://openalex.org/", ""),
            "title": raw.get("title") or "Başlıksız",
            "year": raw.get("publication_year") or "",
            "authors": authors,
            "journal": source.get("display_name") or "",
            "type": raw.get("type") or "unknown",
            "doi": raw.get("doi") or "",
            "volume": biblio.get("volume") or "",
            "issue": biblio.get("issue") or "",
            "pages": pages,
            "is_oa": location.get("is_oa", False),
        }


# ------------------------------------------------------------------ #
#  Yardımcı: Son 1 yılın başlangıç tarihi                             #
# ------------------------------------------------------------------ #
def one_year_ago() -> str:
    return (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

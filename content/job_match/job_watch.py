
"""
job_watch.py
Surveille une liste d'entreprises/labos + job boards via recherches RSS et pages directes,
déduplique les résultats, puis écrit un rapport Markdown dans Obsidian/Quartz.

Installation :
    pip install requests beautifulsoup4 feedparser

Usage :
    python job_watch.py

Fichiers attendus dans le même dossier :
    organizations.csv
    seen_jobs.json  sera créé automatiquement
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime
from urllib.parse import quote_plus, urljoin, urlparse, parse_qs, unquote
import csv
import hashlib
import json
import re
import time
import html

import requests
from bs4 import BeautifulSoup
import feedparser

# === À ADAPTER ===
OBSIDIAN_CONTENT_DIR = Path(r"C:\Users\GOULWEN\Documents\Second_brain\quartz\content")
OUTPUT_DIR = OBSIDIAN_CONTENT_DIR / "Jobs" / "Veille automatique"
ORGANIZATIONS_CSV = Path(__file__).with_name("organizations.csv")
SEEN_JSON = Path(__file__).with_name("seen_jobs.json")

# Mets False si tu veux des résultats plus larges.
STRICT_KEYWORD_FILTER = False

# Requêtes générales. Tu peux en ajouter/supprimer selon ton profil.
ROLE_KEYWORDS = [
    "job", "jobs", "career", "careers", "recruitment", "hiring", "open position",
    "offre emploi", "offres emploi", "recrutement", "carrières", "emploi",
    "stage", "internship", "apprenticeship", "alternance", "CDD", "CDI",
    "research engineer", "ingénieur de recherche", "ingénieur d'étude",
    "biomedical engineer", "medical device", "medtech", "robotics", "biomechanics",
    "data scientist", "machine learning", "AI", "IA", "signal processing",
    "clinical", "R&D", "software engineer", "hardware engineer"
]

# Domaines job boards / ATS / pages carrière à faire remonter via recherche web.
JOB_BOARD_DOMAINS = [
    "linkedin.com/jobs",
    "indeed.com",
    "welcometothejungle.com",
    "apec.fr",
    "euraxess.ec.europa.eu/jobs",
    "academicpositions.com",
    "jobs.lever.co",
    "boards.greenhouse.io",
    "workdayjobs.com",
    "smartrecruiters.com",
    "jobs.ashbyhq.com",
    "breezy.hr",
    "successfactors.com",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 compatible; personal-job-watch/1.0; +local-script"
}

MAX_RESULTS_PER_ORG = 12
REQUEST_SLEEP_SECONDS = 1.0


def load_seen() -> dict:
    if SEEN_JSON.exists():
        return json.loads(SEEN_JSON.read_text(encoding="utf-8"))
    return {"seen": {}}


def save_seen(seen: dict) -> None:
    SEEN_JSON.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")


def clean_text(s: str) -> str:
    s = html.unescape(s or "")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def canonical_url(url: str) -> str:
    url = clean_text(url)
    # Bing RSS renvoie parfois des URLs de redirection.
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    for key in ("url", "u"):
        if key in qs and qs[key]:
            candidate = unquote(qs[key][0])
            if candidate.startswith("http"):
                return candidate
    return url.split("#")[0]


def item_id(url: str, title: str, org: str) -> str:
    raw = f"{canonical_url(url)}|{title}|{org}".lower()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def score_item(title: str, summary: str, org: str) -> int:
    text = f"{title} {summary}".lower()
    score = 0

    job_words = [
        "job", "jobs", "career", "careers", "hiring", "recruitment", "open position",
        "emploi", "recrutement", "offre", "poste", "carrière", "stage", "internship",
        "cdd", "cdi", "alternance", "engineer", "ingénieur", "scientist", "research",
        "r&d", "clinical", "biomedical", "robotics", "medical device", "medtech"
    ]

    for kw in job_words:
        if kw in text:
            score += 2

    org_tokens = [t for t in re.split(r"\W+", org.lower()) if len(t) >= 3]
    if any(t in text for t in org_tokens):
        score += 2

    bad_words = [
        "news", "press release", "communiqué", "webinar", "annual report",
        "financial results", "stock", "investor", "conference"
    ]
    for bw in bad_words:
        if bw in text:
            score -= 2

    return score


def bing_rss_search(query: str, max_items: int = 10) -> list[dict]:
    """
    Utilise le flux RSS de Bing pour éviter de scraper les pages de résultats HTML.
    """
    url = f"https://www.bing.com/search?q={quote_plus(query)}&format=rss"
    feed = feedparser.parse(url)
    items = []
    for entry in feed.entries[:max_items]:
        items.append({
            "title": clean_text(getattr(entry, "title", "")),
            "url": canonical_url(getattr(entry, "link", "")),
            "summary": clean_text(getattr(entry, "summary", "")),
            "source": "bing_rss",
            "query": query,
        })
    return items


def build_queries(org: dict) -> list[str]:
    name = org["name"]
    location = org.get("location_hint", "").strip()
    extra = org.get("extra_keywords", "").strip()

    queries = []

    # Recherche large liée à l'organisation
    queries.append(f'"{name}" jobs OR careers OR recrutement OR emploi OR "open positions"')

    # Recherche avec localisation
    if location:
        queries.append(f'"{name}" ({location}) jobs OR recrutement OR emploi')

    # Recherche orientée profils medtech/recherche
    queries.append(f'"{name}" ("research engineer" OR "ingénieur de recherche" OR R&D OR biomedical OR robotics OR medtech)')

    # Recherche sur job boards / ATS
    for domain in JOB_BOARD_DOMAINS:
        queries.append(f'site:{domain} "{name}" job OR jobs OR emploi OR recrutement')

    if extra:
        queries.append(f'"{name}" {extra} jobs OR recrutement')

    return queries


def fetch_direct_page(url: str) -> list[dict]:
    """
    Récupère une page carrière directe et extrait les liens qui ressemblent à des offres.
    À utiliser pour les URLs ajoutées manuellement dans organizations.csv.
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        return [{
            "title": f"ERREUR accès page directe : {e}",
            "url": url,
            "summary": "",
            "source": "direct_error",
            "query": url,
        }]

    soup = BeautifulSoup(r.text, "html.parser")
    candidates = []

    for a in soup.find_all("a", href=True):
        txt = clean_text(a.get_text(" "))
        href = urljoin(url, a["href"])
        haystack = f"{txt} {href}".lower()

        if len(txt) < 3:
            continue

        if any(k in haystack for k in [
            "job", "career", "recruit", "hiring", "emploi", "recrutement",
            "poste", "stage", "internship", "engineer", "scientist", "cdd", "cdi"
        ]):
            candidates.append({
                "title": txt[:160],
                "url": canonical_url(href),
                "summary": "",
                "source": "direct_page",
                "query": url,
            })

    # Dédup locale
    dedup = {}
    for c in candidates:
        dedup[c["url"]] = c
    return list(dedup.values())[:30]


def read_organizations() -> list[dict]:
    orgs = []
    with ORGANIZATIONS_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("enabled", "").strip().lower() in ("yes", "y", "true", "1", "oui"):
                orgs.append(row)
    return orgs


def markdown_escape(s: str) -> str:
    return s.replace("|", "\\|").strip()


def main() -> None:
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    seen = load_seen()
    seen_map = seen.setdefault("seen", {})

    orgs = read_organizations()
    all_new = []
    all_candidates = []

    for idx, org in enumerate(orgs, start=1):
        name = org["name"].strip()
        print(f"[{idx}/{len(orgs)}] Recherche : {name}")

        candidates = []

        direct_url = org.get("direct_url", "").strip()
        if direct_url:
            candidates.extend(fetch_direct_page(direct_url))
            time.sleep(REQUEST_SLEEP_SECONDS)

        for q in build_queries(org):
            try:
                candidates.extend(bing_rss_search(q, max_items=6))
            except Exception as e:
                candidates.append({
                    "title": f"ERREUR recherche RSS : {e}",
                    "url": "",
                    "summary": "",
                    "source": "bing_error",
                    "query": q,
                })
            time.sleep(REQUEST_SLEEP_SECONDS)

        # Score + filtre + dédup par URL
        by_url = {}
        for c in candidates:
            c["org"] = name
            c["type"] = org.get("type", "")
            c["score"] = score_item(c["title"], c.get("summary", ""), name)
            if STRICT_KEYWORD_FILTER and c["score"] < 2:
                continue
            if c.get("url"):
                by_url[canonical_url(c["url"])] = c

        ranked = sorted(by_url.values(), key=lambda x: x.get("score", 0), reverse=True)
        ranked = ranked[:MAX_RESULTS_PER_ORG]
        all_candidates.extend(ranked)

        for item in ranked:
            uid = item_id(item["url"], item["title"], name)
            if uid not in seen_map:
                item["id"] = uid
                all_new.append(item)
                seen_map[uid] = {
                    "first_seen": date_str,
                    "org": name,
                    "title": item["title"],
                    "url": item["url"],
                }

    # Rapport Markdown
    out = []
    out.append(f"# Jobs trouvés - {date_str}")
    out.append("")
    out.append(f"- Généré le : {now.strftime('%Y-%m-%d %H:%M')}")
    out.append(f"- Organisations surveillées : {len(orgs)}")
    out.append(f"- Nouveaux résultats : {len(all_new)}")
    out.append("")
    out.append("> Note : les job boards type LinkedIn/Indeed/WTTJ sont mieux suivis via leurs alertes natives. Ce script les repère surtout via indexation web/RSS et via les sites carrière directs.")
    out.append("")

    if all_new:
        out.append("## Nouveautés")
        out.append("")
        grouped = {}
        for item in all_new:
            grouped.setdefault(item["org"], []).append(item)

        for org_name in sorted(grouped):
            out.append(f"### {org_name}")
            out.append("")
            for item in sorted(grouped[org_name], key=lambda x: x.get("score", 0), reverse=True):
                title = markdown_escape(item["title"] or "Sans titre")
                url = item["url"]
                source = item.get("source", "")
                score = item.get("score", 0)
                out.append(f"- [{title}]({url})")
                out.append(f"  - Source : `{source}` · Score : `{score}`")
                if item.get("summary"):
                    out.append(f"  - Extrait : {markdown_escape(item['summary'][:240])}")
            out.append("")
    else:
        out.append("## Nouveautés")
        out.append("")
        out.append("Aucune nouvelle offre détectée depuis le dernier passage.")
        out.append("")

    out.append("## Toutes les pistes vues aujourd'hui")
    out.append("")
    out.append("| Organisation | Score | Titre | Source | Lien |")
    out.append("|---|---:|---|---|---|")
    for item in sorted(all_candidates, key=lambda x: (x["org"], -x.get("score", 0))):
        out.append(
            f"| {markdown_escape(item['org'])} | {item.get('score', 0)} | "
            f"{markdown_escape(item.get('title', ''))} | {markdown_escape(item.get('source', ''))} | "
            f"[ouvrir]({item.get('url', '')}) |"
        )

    md_path = OUTPUT_DIR / f"{date_str}_jobs.md"
    md_path.write_text("\n".join(out), encoding="utf-8")
    save_seen(seen)

    print(f"\nRapport écrit : {md_path}")
    print(f"Nouveaux résultats : {len(all_new)}")


if __name__ == "__main__":
    main()

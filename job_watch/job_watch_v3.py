#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
job_watch.py

Surveille des pages carrières / job boards, extrait uniquement des fiches de postes,
publie les URLs validées au fil de l'eau, et associe chaque offre aux compétences du profil.

Usage minimal:
    python job_watch.py --input organisations.csv --out jobs_found.jsonl

Formats d'entrée acceptés:
    - CSV avec colonnes possibles: company, name, organisation, url, direct_url, careers_url, url_1..url_10
    - TXT avec une URL par ligne
    - argument direct: --url https://...

Dépendances recommandées:
    pip install requests beautifulsoup4 lxml pypdf

Recherche ciblée:
    Le script privilégie maintenant les intitulés compatibles avec le profil:
    imagerie médicale, logiciel scientifique, neuroimagerie, medtech, ultrasons/fUS,
    dispositifs médicaux, robotique médicale, ingénierie clinique, Python médical.

Option IA:
    Le script fonctionne sans IA. Si vous voulez activer une classification IA optionnelle:
    pip install openai
    export OPENAI_API_KEY=...
    python job_watch.py --input organisations.csv --use-ai
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import html
import json
import os
import re
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Profil de compétences
# ---------------------------------------------------------------------------

SKILL_TIERS: Dict[str, Dict[str, object]] = {
    "core": {
        "label": "Très maîtrisé / cœur de profil",
        "weight": 4.0,
        "mobilisation": "immédiat",
        "skills": [
            "Python", "MATLAB", "traitement d'images médicales", "imagerie multimodale",
            "échographie", "CT", "tomodensitométrie", "TEP", "PET", "recalage multimodal",
            "MATLAB App Designer", "PyQt5", "visualisation 3D", "validation expérimentale",
            "protocoles expérimentaux", "rédaction technique", "guides utilisateurs", "Git",
            "GitHub", "gestion d'exigences", "documentation ANSM", "dispositifs médicaux",
            "conception de bancs d'essais", "gestion de projet R&D",
            "coordination pluridisciplinaire", "encadrement de stagiaires",
            "modélisation biomédicale", "diagrammes de Gantt", "Overleaf", "Obsidian",
            "anglais C1",
        ],
    },
    "good": {
        "label": "Bon niveau / utilisé en contexte projet réel",
        "weight": 2.5,
        "mobilisation": "court",
        "skills": [
            "ROS", "robotique médicale", "UR3e", "contrôle-commande",
            "planification de trajectoires", "télé-opération", "matrices DH",
            "tests logiciels", "Azure DevOps", "3D Slicer", "simulation HD-sEMG",
            "traitement du signal", "FFT", "convolution", "filtrage", "biomécanique",
            "physiologie", "anatomie", "cycle en V", "ISO 13485",
            "règlement UE 2017/745", "Jira",
        ],
    },
    "intermediate": {
        "label": "Niveau intermédiaire / bases solides mais moins central",
        "weight": 1.4,
        "mobilisation": "moyen",
        "skills": [
            "C", "C++", "C/C++", "DMAIC", "prototypage mécanique",
            "reinforcement learning", "apprentissage par renforcement", "R", "SQL", "VBA",
            "prototypage rapide", "impression 3D", "Fusion 360",
        ],
    },
    "secondary": {
        "label": "Notions / compétences secondaires",
        "weight": 0.4,
        "mobilisation": "long",
        "skills": ["espagnol", "breton"],
    },
}

# Synonymes et variantes fréquentes pour améliorer le matching.
SKILL_SYNONYMS: Dict[str, List[str]] = {
    "Python": ["python", "py"],
    "MATLAB": ["matlab", "app designer", "matlab app designer"],
    "traitement d'images médicales": [
        "traitement d'image", "traitement d’images", "image processing",
        "medical image", "medical imaging", "analyse d'image", "analyse d’images",
    ],
    "imagerie multimodale": ["multimodal", "multi-modal", "multimodality", "multimodal imaging"],
    "échographie": ["ultrasound", "ultrason", "ultrasons", "échographique", "echographie"],
    "CT": ["ct", "scanner", "computed tomography", "tomodensitométrie", "tomodensitometrie"],
    "TEP": ["tep", "pet", "positron emission tomography"],
    "PET": ["pet", "tep", "positron emission tomography"],
    "recalage multimodal": ["registration", "image registration", "recalage", "fusion d'images", "fusion d’images"],
    "PyQt5": ["pyqt", "pyqt5", "qt for python"],
    "visualisation 3D": ["3d visualization", "visualisation 3d", "3d rendering", "vtk", "itk", "3d slicer"],
    "validation expérimentale": ["experimental validation", "validation expérimentale", "phantom", "fantôme", "fantomes", "fantômes"],
    "rédaction technique": ["technical writing", "documentation technique", "rédaction technique"],
    "Git": ["git"],
    "GitHub": ["github"],
    "gestion d'exigences": ["requirements", "exigences", "requirement management"],
    "documentation ANSM": ["ansm", "brochure investigateur", "investigation clinique"],
    "dispositifs médicaux": ["medical device", "dispositif médical", "dispositifs médicaux", "mdr"],
    "gestion de projet R&D": ["r&d", "research and development", "gestion de projet", "project management"],
    "coordination pluridisciplinaire": ["cross-functional", "pluridisciplinaire", "multidisciplinary", "interdisciplinary"],
    "anglais C1": ["english", "anglais", "fluent english", "technical english"],
    "ROS": ["ros", "robot operating system"],
    "robotique médicale": ["medical robotics", "robotique médicale", "surgical robotics", "robotic"],
    "UR3e": ["ur3e", "universal robots"],
    "contrôle-commande": ["control", "commande", "contrôle-commande", "control systems"],
    "planification de trajectoires": ["trajectory", "trajectoire", "path planning"],
    "télé-opération": ["teleoperation", "téléopération", "télé-opération"],
    "tests logiciels": ["unit test", "integration test", "software test", "tests logiciels", "pytest"],
    "Azure DevOps": ["azure devops"],
    "3D Slicer": ["3d slicer", "slicer"],
    "simulation HD-sEMG": ["hd-semg", "semg", "electromyography", "électromyographie"],
    "traitement du signal": ["signal processing", "traitement du signal"],
    "FFT": ["fft", "fourier"],
    "biomécanique": ["biomechanics", "biomécanique", "biomecanique"],
    "physiologie": ["physiology", "physiologie"],
    "anatomie": ["anatomy", "anatomie"],
    "cycle en V": ["v-model", "cycle en v"],
    "ISO 13485": ["iso 13485"],
    "règlement UE 2017/745": ["2017/745", "eu mdr", "mdr", "règlement ue"],
    "Jira": ["jira"],
    "C++": ["c++", "cpp"],
    "C/C++": ["c/c++", "c++", " c "],
    "SQL": ["sql", "mysql", "sqlite", "postgresql"],
    "R": [" r ", "r language"],
    "Fusion 360": ["fusion 360"],
    "impression 3D": ["3d printing", "impression 3d", "additive manufacturing"],
    "reinforcement learning": ["reinforcement learning", "apprentissage par renforcement"],
}


# Mots-clés pour identifier les offres pertinentes à surveiller.
TARGET_JOB_KEYWORDS = [
    "ingénieur", "engineer", "developer", "développeur", "software", "logiciel",
    "scientist", "research", "recherche", "r&d", "image", "imaging", "imagerie",
    "medical", "médical", "biomedical", "biomédical", "robot", "robotics",
    "python", "matlab", "c++", "data", "simulation", "modélisation", "modeling",
    "quality image", "qualité image", "clinical", "clinique", "validation",
]

EXCLUDE_JOB_KEYWORDS = [
    "sales", "commercial", "marketing", "finance", "accounting", "hr ",
    "human resources", "ressources humaines", "juridique", "legal", "procurement",
    "stage commercial", "business development", "alternance commerce",
]


# ---------------------------------------------------------------------------
# Intitulés de postes ciblés FR/EN
# ---------------------------------------------------------------------------
TARGET_ROLE_TITLES: List[str] = [
    "ingénieur r&d imagerie médicale", "ingénieur recherche et développement imagerie médicale",
    "ingénieur logiciel scientifique", "ingénieur développement logiciel scientifique",
    "ingénieur traitement d'images médicales", "ingénieur traitement d’image médicale",
    "ingénieur traitement d'images", "ingénieur analyse d'images", "ingénieur analyse d’images",
    "ingénieur neuroimagerie", "ingénieur dispositifs médicaux", "ingénieur système dispositifs médicaux",
    "ingénieur systèmes dispositifs médicaux", "ingénieur logiciel médical", "ingénieur r&d ultrasons",
    "ingénieur r&d échographie", "ingénieur r&d fUS", "ingénieur robotique médicale",
    "ingénieur innovation medtech", "ingénieur clinique", "ingénieur application clinique",
    "ingénieur python médical", "ingénieur santé", "ingénieur biomédical", "ingénieur biomédicale",
    "medical imaging r&d engineer", "r&d engineer medical imaging", "scientific software engineer",
    "research software engineer", "medical image processing engineer", "image processing engineer",
    "medical imaging engineer", "neuroimaging engineer", "research engineer neurotechnology",
    "neurotechnology research engineer", "medical device engineer", "medical devices engineer",
    "medical device systems engineer", "systems engineer medical devices", "medical software engineer",
    "healthcare software engineer", "ultrasound r&d engineer", "fUS engineer", "functional ultrasound engineer",
    "medical robotics engineer", "surgical robotics engineer", "medtech innovation engineer",
    "clinical engineer", "clinical applications engineer", "medical python engineer", "healthcare engineer",
    "biomedical engineer",
]

TARGET_TITLE_TERMS: Dict[str, List[str]] = {
    "role": ["ingénieur", "ingenieur", "engineer", "développeur", "developpeur", "developer", "scientist", "chercheur", "research", "software"],
    "domain": ["imagerie", "imaging", "image", "medical", "médical", "medicale", "biomedical", "biomédical", "biomedicale", "medtech", "santé", "healthcare", "clinical", "clinique", "ultrasound", "ultrasons", "échographie", "echographie", "neuroimaging", "neuroimagerie", "neurotechnology", "neurotechnologie", "robotique", "robotics", "dispositif médical", "medical device", "fus", "python"],
}

MARKETPLACE_SEARCH_TEMPLATES: Dict[str, str] = {
    "linkedin": "https://www.linkedin.com/jobs/search/?keywords={query}&location={location}",
    "indeed": "https://fr.indeed.com/jobs?q={query}&l={location}",
    "hellowork": "https://www.hellowork.com/fr-fr/emploi/recherche.html?k={query}&l={location}",
}

def normalize_for_match(value: str) -> str:
    value = (value or "").lower()
    value = value.replace("’", "'").replace("œ", "oe")
    value = re.sub(r"[\u2010-\u2015]", "-", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()

def matches_target_role_title(title: str, text: str = "") -> List[str]:
    title_l = normalize_for_match(title)
    text_l = normalize_for_match(text[:2000])
    haystack = f"{title_l} {text_l}"
    matches: List[str] = []
    for role in TARGET_ROLE_TITLES:
        role_l = normalize_for_match(role)
        if role_l and role_l in haystack:
            matches.append(role)
    role_hit = any(term in title_l for term in TARGET_TITLE_TERMS["role"])
    domain_hit = any(term in title_l for term in TARGET_TITLE_TERMS["domain"])
    if role_hit and domain_hit and not matches:
        matches.append("titre compatible profil biomédical / imagerie / logiciel")
    return list(dict.fromkeys(matches))

def title_profile_score(title: str, text: str = "") -> float:
    matches = matches_target_role_title(title, text)
    return 0.0 if not matches else min(12.0, 5.0 + 2.0 * len(matches))

def detect_source_type(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "linkedin." in host: return "linkedin"
    if "indeed." in host: return "indeed"
    if "hellowork." in host: return "hellowork"
    if any(x in host for x in ["lever.co", "greenhouse.io", "workable.com", "workdayjobs.com", "smartrecruiters.com"]): return "ats"
    return "career_site"

def is_probable_career_page(url: str, title: str, text: str) -> Tuple[bool, float, str]:
    url_l = normalize_for_match(url); title_l = normalize_for_match(title); text_l = normalize_for_match(text[:5000])
    source_type = detect_source_type(url)
    if source_type in {"linkedin", "indeed", "hellowork", "ats"}:
        return True, 0.95, f"Source de type {source_type}."
    career_url_terms = ["career", "careers", "carriere", "carrières", "emploi", "emplois", "offres", "jobs", "recrutement", "recruitment", "join-us", "nous-rejoindre", "talent", "vacancies", "openings"]
    career_content_terms = ["nos offres", "offres d'emploi", "job openings", "open positions", "rejoignez-nous", "join us", "candidatez", "postuler", "apply now", "recruitment", "recrutement", "careers", "carrières", "voir les offres", "search jobs", "rechercher une offre"]
    url_score = sum(term in url_l for term in career_url_terms)
    title_score = sum(term in title_l for term in career_url_terms)
    text_score = sum(term in text_l for term in career_content_terms)
    score = url_score * 0.3 + title_score * 0.25 + text_score * 0.15
    if url_score + title_score + text_score >= 2:
        return True, min(0.95, 0.55 + score), "Page source compatible carrière/recrutement."
    return False, 0.45, "La source ne ressemble pas clairement à une page carrière."

def build_marketplace_sources(marketplaces: Sequence[str], role_queries: Sequence[str], location: str) -> List[Tuple[str, str]]:
    sources: List[Tuple[str, str]] = []
    safe_location = quote(location or "France")
    for marketplace in marketplaces:
        m = marketplace.strip().lower()
        template = MARKETPLACE_SEARCH_TEMPLATES.get(m)
        if not template: continue
        for query in role_queries:
            sources.append((f"{m} search: {query}", template.format(query=quote(query), location=safe_location)))
    return sources


# ---------------------------------------------------------------------------
# Filtres URL et contenu
# ---------------------------------------------------------------------------

BAD_URL_PATTERNS = [
    r"/about(?:/|$)", r"/about-us(?:/|$)", r"/company(?:/|$)",
    r"/careers?/?$", r"/jobs?/?$", r"/join-us/?$", r"/nous-rejoindre/?$",
    r"/recrutement/?$", r"/talent/?$", r"/contact(?:/|$)",
    r"/privacy(?:/|$)", r"/legal(?:/|$)", r"/terms(?:/|$)",
    r"/cookies(?:/|$)", r"/blog(?:/|$)", r"/news(?:/|$)",
    r"/events?(?:/|$)", r"/login(?:/|$)", r"/signup(?:/|$)",
    r"/spontaneous", r"/candidature-spontanee", r"/candidature_spontanee",
    r"/candidate-profile", r"/profile", r"/search/?$",
]

GOOD_JOB_URL_PATTERNS = [
    r"/job/", r"/jobs/.+", r"/careers/jobs/.+", r"/career/.+",
    r"/positions?/.+", r"/open-position", r"/opening",
    r"/offre-de-emploi/.+", r"/offres-emploi/.+", r"/emploi/.+",
    r"/requisition/.+", r"/req/.+", r"/posting/.+", r"/apply/.+",
    r"jobid=", r"job_id=", r"gh_jid=", r"requisitionid=", r"reqid=",
    r"lever\.co/.+/.+", r"greenhouse\.io/.+", r"workable\.com/.+",
    r"myworkdayjobs\.com/.+", r"welcomekit\.co/.+", r"jobs\.smartrecruiters\.com/.+/.+",
    r"linkedin\.com/jobs/view/", r"indeed\.[a-z.]+/viewjob", r"jk=",
    r"hellowork\.com/.+/emplois/.+", r"hellowork\.com/.+/emploi/.+",
    r"\.pdf(?:$|[?#])",
]

JOB_CONTENT_SIGNALS = [
    "postuler", "candidater", "apply", "apply now", "job description",
    "description du poste", "missions", "responsibilities", "responsabilités",
    "qualifications", "requirements", "profil recherché", "compétences",
    "contrat", "type de contrat", "location", "localisation", "rémunération",
    "salary", "about the role", "your role", "vos missions", "job requisition",
]

LIST_PAGE_SIGNALS = [
    "search jobs", "rechercher", "nos offres", "job alerts", "create alert",
    "voir les offres", "toutes nos offres", "open positions", "job openings",
    "filter by", "filtrer", "keyword", "mot-clé",
]

# Filtres demandés : France/Suisse uniquement, offres publiées en 2026,
# exclusion stage/alternance/senior/responsable, exclusion doctorat demandé
# (les offres de PhD restent autorisées), exclusion > 5 ans d'expérience.
ALLOWED_COUNTRY_TERMS = [
    "france", "paris", "lyon", "marseille", "grenoble", "toulouse", "nantes",
    "montpellier", "strasbourg", "lille", "rennes", "saclay", "bordeaux",
    "switzerland", "suisse", "geneva", "genève", "lausanne", "bern", "berne",
    "zurich", "zürich", "basel", "bâle", "neuchâtel", "neuchatel", "fribourg",
]

EXCLUDED_ROLE_TERMS = [
    "alternance", "apprentissage", "apprenticeship", "stage", "stagiaire",
    "internship", "intern ", "senior", "sr.", "lead ", "principal",
    "responsable", "manager", "head of", "directeur", "directrice",
]

PHD_OFFER_TERMS = ["phd", "ph.d", "doctorant", "doctorante", "thèse", "these", "doctoral candidate"]

DOCTORATE_REQUIREMENT_PATTERNS = [
    r"(?:doctorat|phd|ph\.d|doctoral degree)\s+(?:requis|required|obligatoire|mandatory)",
    r"(?:requires|required|required qualifications?.{0,80})(?:doctorat|phd|ph\.d|doctoral degree)",
    r"(?:vous avez|you have).{0,80}(?:doctorat|phd|ph\.d)",
]

EXPERIENCE_PATTERNS = [
    r"(\d+)\s*(?:\+|plus)?\s*(?:ans|années|years)\s+(?:d['’ ]expérience|experience)",
    r"(?:minimum|min\.?|at least|au moins)\s*(\d+)\s*(?:ans|années|years)",
    r"(?:experience|expérience).{0,30}(\d+)\s*(?:\+|plus)?\s*(?:ans|années|years)",
]


@dataclasses.dataclass
class JobResult:
    url: str
    source_url: str
    company: str
    title: str
    location: str
    contract_type: str
    published_at: str
    found_at: str
    score: float
    mobilisation_time: str
    matched_skills: Dict[str, List[str]]
    missing_or_weak_keywords: List[str]
    snippet: str
    classification_confidence: float
    classification_reason: str
    title_profile_matches: List[str] = dataclasses.field(default_factory=list)
    career_page_verified: bool = False
    source_type: str = "career_site"


# ---------------------------------------------------------------------------
# Utilitaires réseau / parsing
# ---------------------------------------------------------------------------

def normalize_url(url: str) -> str:
    url = html.unescape((url or "").strip())
    if not url:
        return ""
    parsed = urlparse(url)
    if not parsed.scheme:
        url = "https://" + url
        parsed = urlparse(url)

    # Supprime fragments et paramètres de tracking.
    query = parse_qs(parsed.query)
    query = {
        k: v for k, v in query.items()
        if not k.lower().startswith(("utm_", "fbclid", "gclid"))
    }
    clean_query = urlencode(query, doseq=True)
    parsed = parsed._replace(fragment="", query=clean_query)
    return urlunparse(parsed)


def same_domain_or_ats(source_url: str, candidate_url: str) -> bool:
    src = urlparse(source_url).netloc.lower().replace("www.", "")
    cand = urlparse(candidate_url).netloc.lower().replace("www.", "")
    ats_domains = [
        "lever.co", "greenhouse.io", "myworkdayjobs.com", "workable.com",
        "smartrecruiters.com", "welcomekit.co", "successfactors", "talent-soft.com",
        "softgarden.io", "teamtailor.com", "recruitee.com",
        "linkedin.com", "indeed.com", "indeed.fr", "hellowork.com",
    ]
    return src in cand or cand in src or any(d in cand for d in ats_domains)


def extract_pdf_text(content: bytes) -> str:
    """Extrait le texte d'une offre PDF sans OCR. Nécessite idéalement pypdf."""
    try:
        from pypdf import PdfReader  # type: ignore
        import io
        reader = PdfReader(io.BytesIO(content))
        pages = []
        for page in reader.pages[:15]:
            pages.append(page.extract_text() or "")
        return re.sub(r"\s+", " ", " ".join(pages)).strip()
    except Exception:
        # Dernier recours : extraction naïve des chaînes lisibles.
        try:
            decoded = content.decode("latin-1", errors="ignore")
            decoded = re.sub(r"[^A-Za-zÀ-ÿ0-9@:/._+%#€$£\-(),; '\n]", " ", decoded)
            return re.sub(r"\s+", " ", decoded).strip()
        except Exception:
            return ""


def fetch_url(session: requests.Session, url: str, timeout: int = 20) -> Optional[str]:
    try:
        resp = session.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; JobWatch/2.0; "
                    "+https://example.local/job-watch)"
                ),
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            },
            allow_redirects=True,
        )
        if resp.status_code >= 400:
            return None
        ctype = resp.headers.get("content-type", "").lower()
        is_pdf = "application/pdf" in ctype or urlparse(resp.url).path.lower().endswith(".pdf")
        if is_pdf:
            pdf_text = extract_pdf_text(resp.content)
            if not pdf_text:
                return None
            title = Path(urlparse(resp.url).path).name or "Offre PDF"
            return f"<html><head><title>{html.escape(title)}</title></head><body><pre>{html.escape(pdf_text)}</pre></body></html>"
        if "text/html" not in ctype and "application/json" not in ctype and not resp.text.lstrip().startswith(("{", "[")):
            return None
        return resp.text
    except requests.RequestException:
        return None


def soup_text(html_text: str) -> Tuple[str, str, BeautifulSoup]:
    soup = BeautifulSoup(html_text or "", "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return title, text, soup


def extract_links(source_url: str, html_text: str) -> List[str]:
    _, _, soup = soup_text(html_text)
    links: List[str] = []
    for a in soup.find_all("a", href=True):
        href = normalize_url(urljoin(source_url, a.get("href", "")))
        if href and href.startswith(("http://", "https://")):
            links.append(href)
    return list(dict.fromkeys(links))


def extract_jsonld_jobs(html_text: str, base_url: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html_text or "", "lxml")
    jobs: List[Dict[str, str]] = []
    for script in soup.find_all("script", type=lambda t: t and "ld+json" in t):
        raw = script.get_text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                jobs.append({
                    "title": str(item.get("title", "")),
                    "location": json.dumps(item.get("jobLocation", ""), ensure_ascii=False),
                    "contract_type": str(item.get("employmentType", "")),
                    "url": normalize_url(str(item.get("url", base_url))),
                    "published_at": str(item.get("datePosted", "")),
                })
    return jobs


# ---------------------------------------------------------------------------
# Connecteurs ATS simples
# ---------------------------------------------------------------------------

def discover_ats_api_urls(source_url: str) -> List[str]:
    """
    Génère des endpoints connus quand l'URL correspond à un ATS public.
    Le script garde aussi le scraping générique si aucun connecteur ne marche.
    """
    u = normalize_url(source_url)
    p = urlparse(u)
    host = p.netloc.lower()
    path = p.path.strip("/")
    urls: List[str] = []

    # Lever: https://jobs.lever.co/company
    if "jobs.lever.co" in host:
        parts = path.split("/")
        if parts and parts[0]:
            company = parts[0]
            urls.append(f"https://api.lever.co/v0/postings/{company}?mode=json")

    # Greenhouse board: https://boards.greenhouse.io/company
    if "boards.greenhouse.io" in host:
        parts = path.split("/")
        if parts and parts[0]:
            company = parts[0]
            urls.append(f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true")

    # Workable: https://apply.workable.com/company/
    if "apply.workable.com" in host:
        parts = path.split("/")
        if parts and parts[0]:
            company = parts[0]
            urls.append(f"https://apply.workable.com/api/v1/widget/accounts/{company}?details=true")

    return urls


def parse_ats_json(api_url: str, payload: str, company: str, source_url: str) -> List[JobResult]:
    found_at = datetime.now(timezone.utc).isoformat()
    out: List[JobResult] = []
    try:
        data = json.loads(payload)
    except Exception:
        return out

    # Lever
    if "api.lever.co" in api_url and isinstance(data, list):
        for item in data:
            text = " ".join([
                str(item.get("text", "")),
                str(item.get("descriptionPlain", "")),
                str(item.get("categories", "")),
            ])
            url = normalize_url(str(item.get("hostedUrl", item.get("applyUrl", ""))))
            if not url:
                continue
            score_data = score_against_profile(str(item.get("text", "")), text)
            out.append(JobResult(
                url=url,
                source_url=source_url,
                company=company,
                title=str(item.get("text", "")),
                location=str((item.get("categories") or {}).get("location", "")),
                contract_type=str((item.get("categories") or {}).get("commitment", "")),
                published_at=str(item.get("createdAt", "")),
                found_at=found_at,
                score=score_data["score"],
                mobilisation_time=score_data["mobilisation_time"],
                matched_skills=score_data["matched_skills"],
                missing_or_weak_keywords=score_data["missing_or_weak_keywords"],
                snippet=make_snippet(text),
                classification_confidence=0.95,
                classification_reason="ATS Lever: fiche de poste individuelle.",
            ))

    # Greenhouse
    if "greenhouse" in api_url and isinstance(data, dict):
        for item in data.get("jobs", []):
            text = " ".join([str(item.get("title", "")), str(item.get("content", ""))])
            url = normalize_url(str(item.get("absolute_url", "")))
            if not url:
                continue
            offices = item.get("offices") or []
            loc = ", ".join(o.get("name", "") for o in offices if isinstance(o, dict))
            score_data = score_against_profile(str(item.get("title", "")), text)
            out.append(JobResult(
                url=url,
                source_url=source_url,
                company=company,
                title=str(item.get("title", "")),
                location=loc,
                contract_type="",
                published_at=str(item.get("updated_at", "")),
                found_at=found_at,
                score=score_data["score"],
                mobilisation_time=score_data["mobilisation_time"],
                matched_skills=score_data["matched_skills"],
                missing_or_weak_keywords=score_data["missing_or_weak_keywords"],
                snippet=make_snippet(BeautifulSoup(text, "lxml").get_text(" ", strip=True)),
                classification_confidence=0.95,
                classification_reason="ATS Greenhouse: fiche de poste individuelle.",
            ))

    return out


# ---------------------------------------------------------------------------
# Classification offre individuelle
# ---------------------------------------------------------------------------

def looks_like_job_url(url: str) -> bool:
    url_l = normalize_url(url).lower()
    if not url_l.startswith(("http://", "https://")):
        return False
    if any(re.search(pattern, url_l) for pattern in BAD_URL_PATTERNS):
        return False
    return any(re.search(pattern, url_l) for pattern in GOOD_JOB_URL_PATTERNS)


def detect_title(title: str, text: str) -> str:
    candidates = []
    if title:
        cleaned = re.split(r"[-|—–]", title)[0].strip()
        candidates.append(cleaned)

    patterns = [
        r"(?:poste|offre)\s*[:\-]\s*([A-ZÉÈÀÂÊÎÔÛÇa-z0-9 /\-\(\)]+)",
        r"(Ing[ée]nieur[^\n\.]{3,100})",
        r"(Software Engineer[^\n\.]{0,80})",
        r"(Research Engineer[^\n\.]{0,80})",
        r"(Développeur[^\n\.]{0,80})",
        r"(Data Scientist[^\n\.]{0,80})",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            candidates.append(m.group(1).strip())

    for c in candidates:
        c = re.sub(r"\s+", " ", c)
        if 5 <= len(c) <= 140:
            return c
    return title[:140] if title else ""


def extract_location(text: str) -> str:
    patterns = [
        r"(?:localisation|lieu de travail|location|site)\s*[:\-]\s*([A-Za-zÀ-ÿ0-9 ,\-\(\)]{2,80})",
        r"\b(Paris|Buc|Marseille|Lyon|Grenoble|Brest|Saclay|Toulouse|Nantes|Montpellier|Strasbourg|Lille|Rennes|France|Remote|Télétravail|Hybrid|Hybride)\b",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            return re.sub(r"\s+", " ", m.group(1) if m.groups() else m.group(0)).strip()[:100]
    return ""


def extract_contract_type(text: str) -> str:
    for keyword in ["CDI", "CDD", "Stage", "Internship", "Thèse", "PhD", "Postdoc", "Alternance", "Permanent", "Fixed-term"]:
        if re.search(rf"\b{re.escape(keyword)}\b", text, flags=re.IGNORECASE):
            return keyword
    m = re.search(r"(type de contrat|contract type)\s*[:\-]\s*([A-Za-zÀ-ÿ0-9 \-/]{2,60})", text, flags=re.IGNORECASE)
    return m.group(2).strip() if m else ""


def is_phd_offer(title: str, text: str) -> bool:
    haystack = normalize_for_match(f"{title} {text[:3000]}")
    return any(term in haystack for term in PHD_OFFER_TERMS)


def is_phd_offer_title(title: str, contract_type: str = "") -> bool:
    haystack = normalize_for_match(f"{title} {contract_type}")
    return any(term in haystack for term in PHD_OFFER_TERMS)


def extract_publication_year(value: str, text: str = "") -> Optional[int]:
    haystack = f"{value or ''} {text[:4000] or ''}"
    # ISO / formats numériques courants.
    for pat in [r"\b(20\d{2})[-/](?:0?[1-9]|1[0-2])[-/](?:0?[1-9]|[12]\d|3[01])\b",
                r"\b(?:0?[1-9]|[12]\d|3[01])[-/](?:0?[1-9]|1[0-2])[-/](20\d{2})\b"]:
        m = re.search(pat, haystack)
        if m:
            return int(m.group(1))
    # Dates textuelles FR/EN avec année.
    m = re.search(r"\b(?:janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre|january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},?\s+(20\d{2})\b", haystack, flags=re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(?:publié|publiée|posted|date posted|publication).{0,60}\b(20\d{2})\b", haystack, flags=re.I)
    if m:
        return int(m.group(1))
    return None


def passes_publication_year_filter(published_at: str, text: str, published_year: Optional[int], allow_unknown: bool) -> Tuple[bool, str]:
    if not published_year:
        return True, "Filtre année désactivé."
    year = extract_publication_year(published_at, text)
    if year is None:
        return (True, "Date de publication inconnue acceptée.") if allow_unknown else (False, f"Date de publication inconnue, filtre {published_year} strict.")
    if year == published_year:
        return True, f"Offre publiée en {published_year}."
    return False, f"Offre publiée en {year}, hors filtre {published_year}."


def detect_max_experience_years(text: str) -> Optional[int]:
    haystack = normalize_for_match(text[:6000])
    years: List[int] = []
    for pat in EXPERIENCE_PATTERNS:
        for m in re.finditer(pat, haystack, flags=re.I):
            try:
                years.append(int(m.group(1)))
            except Exception:
                pass
    return max(years) if years else None


def has_doctorate_requirement(title: str, text: str, contract_type: str = "") -> bool:
    # On garde les offres clairement intitulées PhD/doctorant, mais on exclut les postes
    # ingénieur/chercheur qui exigent déjà un doctorat.
    if is_phd_offer_title(title, contract_type):
        return False
    haystack = normalize_for_match(f"{title} {text[:6000]}")
    return any(re.search(pat, haystack, flags=re.I) for pat in DOCTORATE_REQUIREMENT_PATTERNS)


def passes_location_filter(location: str, text: str, allowed_terms: Sequence[str]) -> Tuple[bool, str]:
    if not allowed_terms:
        return True, "Filtre pays désactivé."
    haystack = normalize_for_match(f"{location} {text[:3000]}")
    if any(normalize_for_match(term) in haystack for term in allowed_terms):
        return True, "Localisation France/Suisse détectée."
    return False, "Localisation France/Suisse non détectée."


def passes_job_constraints(title: str, text: str, location: str, contract_type: str, published_at: str, published_year: Optional[int], allow_unknown_published_date: bool, allowed_country_terms: Sequence[str], max_experience_years: int = 5) -> Tuple[bool, str]:
    haystack = normalize_for_match(f"{title} {contract_type} {text[:6000]}")
    phd_offer = is_phd_offer(title, text)

    # Exclusions stage/alternance/senior/responsable/manager ; PhD conservé.
    if not phd_offer:
        for term in EXCLUDED_ROLE_TERMS:
            if normalize_for_match(term) in haystack:
                return False, f"Exclusion rôle/contrat: {term.strip()}."

    exp_years = detect_max_experience_years(text)
    if exp_years is not None and exp_years > max_experience_years:
        return False, f"Expérience demandée: {exp_years} ans (> {max_experience_years})."

    if has_doctorate_requirement(title, text, contract_type):
        return False, "Doctorat déjà requis pour le poste."

    ok_year, why_year = passes_publication_year_filter(published_at, text, published_year, allow_unknown_published_date)
    if not ok_year:
        return False, why_year

    ok_loc, why_loc = passes_location_filter(location, text, allowed_country_terms)
    if not ok_loc:
        return False, why_loc

    return True, "; ".join(x for x in [why_year, why_loc] if x)


def classify_job_page(url: str, title: str, text: str) -> Tuple[bool, float, str]:
    """
    Retourne (is_individual_job_posting, confidence, reason).
    Filtrage strict pour éviter de publier des pages carrières génériques.
    """
    url_l = url.lower()
    title_l = (title or "").lower()
    text_l = (text or "").lower()

    if any(bad in title_l for bad in ["careers", "carrières", "job search", "rechercher un emploi", "home"]):
        if sum(s in text_l for s in JOB_CONTENT_SIGNALS) < 5:
            return False, 0.75, "Titre de page carrière ou recherche, pas une fiche individuelle."

    if any(signal in text_l for signal in LIST_PAGE_SIGNALS) and sum(s in text_l for s in JOB_CONTENT_SIGNALS) < 5:
        return False, 0.7, "Signaux de liste d'offres sans structure suffisante de fiche poste."

    if not looks_like_job_url(url_l):
        # Exceptions: JSON-LD JobPosting peut sauver une URL atypique.
        if "jobposting" not in text_l:
            return False, 0.7, "URL ne ressemble pas à une fiche de poste individuelle."

    detected_title = detect_title(title, text)
    title_matches = matches_target_role_title(detected_title, text)

    content_score = sum(signal in text_l for signal in JOB_CONTENT_SIGNALS)
    title_score = sum(keyword in title_l for keyword in TARGET_JOB_KEYWORDS)
    target_score = sum(keyword in text_l for keyword in TARGET_JOB_KEYWORDS)
    exclude_score = sum(keyword in text_l for keyword in EXCLUDE_JOB_KEYWORDS)

    has_job_structure = content_score >= 3
    has_job_title = title_score >= 1 or bool(detected_title)
    is_relevant_domain = target_score >= 2 or bool(title_matches)

    if exclude_score >= 2 and target_score < 4:
        return False, 0.8, "Offre probablement hors cible métier."

    if has_job_structure and has_job_title and is_relevant_domain:
        confidence = min(0.98, 0.55 + content_score * 0.06 + title_score * 0.08 + target_score * 0.015 + (0.08 if title_matches else 0))
        reason = "Structure de fiche poste, titre détecté et domaine compatible."
        if title_matches:
            reason += " Intitulé compatible profil: " + ", ".join(title_matches[:3])
        return True, confidence, reason

    return False, 0.55, "La page ne contient pas assez de signaux d'une offre individuelle pertinente."


def ai_classify_job_page(url: str, title: str, text: str) -> Optional[Tuple[bool, float, str]]:
    """
    Classification IA optionnelle. Nécessite OPENAI_API_KEY et package openai.
    Le script reste pleinement fonctionnel sans cette option.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        from openai import OpenAI
    except Exception:
        return None

    client = OpenAI(api_key=api_key)
    prompt = {
        "url": url,
        "title": title[:300],
        "text_excerpt": text[:3500],
        "classes": [
            "individual_job_posting",
            "job_list_page",
            "generic_careers_page",
            "spontaneous_application_page",
            "non_job_page",
        ],
        "instruction": (
            "Classify the page. Keep only individual_job_posting if it has a precise job title, "
            "missions/responsibilities, requirements/skills, location or contract/apply information."
        ),
    }
    try:
        response = client.chat.completions.create(
            model=os.getenv("JOB_WATCH_OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": "You are a strict job-page classifier. Return JSON only."},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content or "{}")
        klass = data.get("class", "")
        conf = float(data.get("confidence", 0.0))
        reason = str(data.get("reason", "Classification IA."))
        return klass == "individual_job_posting", conf, f"IA: {reason}"
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Scoring compétences / temps de mobilisation
# ---------------------------------------------------------------------------

def skill_patterns(skill: str) -> List[str]:
    variants = [skill] + SKILL_SYNONYMS.get(skill, [])
    patterns = []
    for v in variants:
        v = v.strip().lower()
        if not v:
            continue
        if re.fullmatch(r"[a-z0-9+#./ -]+", v):
            patterns.append(r"(?<![a-z0-9])" + re.escape(v) + r"(?![a-z0-9])")
        else:
            patterns.append(re.escape(v))
    return patterns


def find_skill_matches(text: str) -> Dict[str, List[str]]:
    text_l = " " + (text or "").lower() + " "
    matches: Dict[str, List[str]] = {"core": [], "good": [], "intermediate": [], "secondary": []}
    for tier, info in SKILL_TIERS.items():
        for skill in info["skills"]:  # type: ignore[index]
            for pat in skill_patterns(str(skill)):
                if re.search(pat, text_l, flags=re.IGNORECASE):
                    matches[tier].append(str(skill))
                    break
    # dédoublonne sans perdre l'ordre
    return {tier: list(dict.fromkeys(vals)) for tier, vals in matches.items()}


def infer_missing_keywords(text: str) -> List[str]:
    """
    Repère les technologies demandées qui ne sont pas dans le cœur profil,
    utile pour savoir où porter l'effort de montée en compétence.
    """
    watched = [
        "JavaScript", "TypeScript", "React", "Angular", "Vue", "Node.js", "Docker",
        "Kubernetes", "CI/CD", "Jenkins", "GitLab CI", "Qt", "ITK", "VTK",
        "Fiji", "Napari", "CellProfiler", "OMERO", "PyTorch", "TensorFlow",
        "Dask", "xarray", "Zarr", "HPC", "Cloud", "Qiskit", "NeRF", "3DGS",
        "MicMac", "Meshroom", "Three.js", "A-Frame", "CMake", "Rust",
        "mammography", "mammographie", "rayons X", "X-ray",
    ]
    text_l = text.lower()
    hits = []
    for w in watched:
        if w.lower() in text_l:
            hits.append(w)
    return list(dict.fromkeys(hits))


def score_against_profile(title: str, text: str) -> Dict[str, object]:
    full_text = f"{title}\n{text}"
    matches = find_skill_matches(full_text)
    raw = 0.0
    for tier, skills in matches.items():
        raw += len(skills) * float(SKILL_TIERS[tier]["weight"])

    title_matches = matches_target_role_title(title, text)
    raw += title_profile_score(title, text)

    # Bonus domaine biomédical/imagerie/logiciel
    domain_bonus = 0.0
    domain_text = full_text.lower()
    for kw in ["medical", "médical", "biomedical", "biomédical", "imaging", "imagerie", "image", "robot", "clinical", "clinique"]:
        if kw in domain_text:
            domain_bonus += 1.2
    raw += min(domain_bonus, 8.0)

    # Score borné 0-100 avec saturation douce.
    score = round(min(100.0, 100.0 * raw / 45.0), 1)

    core_n = len(matches["core"])
    good_n = len(matches["good"])
    inter_n = len(matches["intermediate"])
    missing = infer_missing_keywords(full_text)

    if score >= 78 and core_n >= 4:
        mobilisation = "immédiat à court"
    elif score >= 62 and (core_n >= 2 or good_n >= 3):
        mobilisation = "court"
    elif score >= 42:
        mobilisation = "moyen"
    else:
        mobilisation = "long"

    # Si beaucoup d'outils hors profil sont demandés, allonge légèrement.
    if len(missing) >= 6 and mobilisation == "court":
        mobilisation = "court à moyen"
    if len(missing) >= 8 and mobilisation == "moyen":
        mobilisation = "moyen à long"

    return {
        "score": score,
        "mobilisation_time": mobilisation,
        "matched_skills": matches,
        "missing_or_weak_keywords": missing,
        "title_profile_matches": title_matches,
    }


def make_snippet(text: str, max_len: int = 600) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:max_len] + ("..." if len(text) > max_len else "")


# ---------------------------------------------------------------------------
# I/O incrémental
# ---------------------------------------------------------------------------

def stable_id(url: str) -> str:
    return hashlib.sha1(normalize_url(url).encode("utf-8")).hexdigest()[:16]


def load_seen(out_path: Path) -> Set[str]:
    seen: Set[str] = set()
    if not out_path.exists():
        return seen
    with out_path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                item = json.loads(line)
                if item.get("url"):
                    seen.add(normalize_url(item["url"]))
            except Exception:
                continue
    return seen


def append_jsonl(out_path: Path, job: JobResult) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data = dataclasses.asdict(job)
    data["id"] = stable_id(job.url)
    with out_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")
        f.flush()


def append_csv(csv_path: Path, job: JobResult) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    exists = csv_path.exists()
    row = {
        "found_at": job.found_at,
        "company": job.company,
        "title": job.title,
        "location": job.location,
        "contract_type": job.contract_type,
        "score": job.score,
        "mobilisation_time": job.mobilisation_time,
        "url": job.url,
        "core_skills": ", ".join(job.matched_skills.get("core", [])),
        "good_skills": ", ".join(job.matched_skills.get("good", [])),
        "intermediate_skills": ", ".join(job.matched_skills.get("intermediate", [])),
        "missing_or_weak_keywords": ", ".join(job.missing_or_weak_keywords),
        "classification_confidence": job.classification_confidence,
        "classification_reason": job.classification_reason,
        "title_profile_matches": ", ".join(job.title_profile_matches),
        "career_page_verified": job.career_page_verified,
        "source_type": job.source_type,
        "source_url": job.source_url,
    }
    with csv_path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not exists:
            writer.writeheader()
        writer.writerow(row)
        f.flush()


def publish_job(job: JobResult, out_path: Path, csv_path: Optional[Path]) -> None:
    """
    Publie l'offre immédiatement:
    - stdout lisible
    - append JSONL
    - append CSV optionnel
    """
    print("\n✅ Offre validée")
    print(f"   Entreprise : {job.company or 'N/A'}")
    print(f"   Poste      : {job.title or 'N/A'}")
    print(f"   Score      : {job.score}/100")
    print(f"   Mobilisation compétences : {job.mobilisation_time}")
    print(f"   Source     : {job.source_type} | page carrière vérifiée: {job.career_page_verified}")
    if job.title_profile_matches:
        print(f"   Intitulé   : {', '.join(job.title_profile_matches[:3])}")
    print(f"   URL        : {job.url}")
    core = ", ".join(job.matched_skills.get("core", [])[:8])
    good = ", ".join(job.matched_skills.get("good", [])[:8])
    if core:
        print(f"   Cœur profil: {core}")
    if good:
        print(f"   Bon niveau : {good}")
    print("", flush=True)

    append_jsonl(out_path, job)
    if csv_path:
        append_csv(csv_path, job)


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def split_multi_urls(value: str) -> List[str]:
    if not value:
        return []
    # Accepte plusieurs liens dans une cellule: séparés par ;, virgule, espace ou retour ligne.
    raw_parts = re.split(r"[;\n\r\t ]+", value.strip())
    return [normalize_url(p.strip().strip(',')) for p in raw_parts if p.strip().startswith(("http://", "https://")) or "." in p.strip()]


def read_sources(input_path: Optional[Path], urls: Sequence[str]) -> List[Tuple[str, str]]:
    """
    Retourne [(company, url)].
    Supporte plusieurs liens par organisation/labo via colonnes:
    direct_url, careers_url, url, URL, jobs_url, url_1..url_10, direct_url_1..direct_url_10,
    linkedin_jobs_url, indeed_jobs_url, hellowork_jobs_url.
    """
    sources: List[Tuple[str, str]] = []
    for u in urls:
        sources.append(("", normalize_url(u)))

    if not input_path:
        return [(c, u) for c, u in sources if u]

    if not input_path.exists():
        raise FileNotFoundError(f"Fichier introuvable: {input_path}")

    if input_path.suffix.lower() == ".csv":
        with input_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                enabled = normalize_for_match(row.get("enabled", "yes"))
                if enabled in {"no", "non", "false", "0"}:
                    continue
                company = (
                    row.get("company") or row.get("name") or row.get("organisation")
                    or row.get("organization") or row.get("laboratoire") or ""
                ).strip()
                url_fields = [
                    "direct_url", "careers_url", "jobs_url", "url", "URL",
                    "linkedin_jobs_url", "indeed_jobs_url", "hellowork_jobs_url",
                ]
                url_fields += [f"url_{i}" for i in range(1, 11)]
                url_fields += [f"direct_url_{i}" for i in range(1, 11)]
                url_fields += [f"careers_url_{i}" for i in range(1, 11)]
                for field in url_fields:
                    for url in split_multi_urls(row.get(field, "") or ""):
                        if url:
                            sources.append((company, url))
    else:
        with input_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                sources.append(("", normalize_url(line)))

    dedup: Dict[str, str] = {}
    for company, url in sources:
        if url:
            dedup[url] = company
    return [(company, url) for url, company in dedup.items()]


# ---------------------------------------------------------------------------
# Crawling maîtrisé
# ---------------------------------------------------------------------------

def generate_pagination_urls(source_url: str, max_pages: int) -> List[str]:
    """
    Pagination générique limitée. Ne remplace pas les connecteurs ATS.
    """
    urls = [source_url]
    parsed = urlparse(source_url)

    for page in range(2, max_pages + 1):
        # ?page=N
        q = parse_qs(parsed.query)
        q["page"] = [str(page)]
        urls.append(urlunparse(parsed._replace(query=urlencode(q, doseq=True))))

        # /page/N
        path = parsed.path.rstrip("/") + f"/page/{page}"
        urls.append(urlunparse(parsed._replace(path=path, query="")))

    return list(dict.fromkeys(urls))


def crawl_source(
    session: requests.Session,
    company: str,
    source_url: str,
    max_depth: int,
    max_pages: int,
    delay: float,
    use_ai: bool,
    min_score: float,
    out_path: Path,
    csv_path: Optional[Path],
    seen: Set[str],
    published_year: Optional[int],
    allow_unknown_published_date: bool,
    allowed_country_terms: Sequence[str],
) -> None:
    print(f"\n🔎 Source: {company or urlparse(source_url).netloc} — {source_url}", flush=True)

    # 1) Connecteurs ATS connus.
    for api_url in discover_ats_api_urls(source_url):
        payload = fetch_url(session, api_url)
        if not payload:
            continue
        for job in parse_ats_json(api_url, payload, company, source_url):
            ok_constraints, why_constraints = passes_job_constraints(
                job.title, job.snippet, job.location, job.contract_type, job.published_at,
                published_year, allow_unknown_published_date, allowed_country_terms,
            )
            if job.url not in seen and job.score >= min_score and ok_constraints:
                job.career_page_verified = True
                job.source_type = detect_source_type(job.url)
                job.classification_reason = f"{job.classification_reason} {why_constraints}".strip()
                if not job.title_profile_matches:
                    job.title_profile_matches = matches_target_role_title(job.title, job.snippet)
                seen.add(job.url)
                publish_job(job, out_path, csv_path)
        time.sleep(delay)

    # 2) Crawling générique contrôlé.
    queue: deque[Tuple[str, int]] = deque()
    for u in generate_pagination_urls(source_url, max_pages=max_pages):
        queue.append((u, 0))

    visited: Set[str] = set()

    while queue:
        current_url, depth = queue.popleft()
        current_url = normalize_url(current_url)
        if current_url in visited:
            continue
        visited.add(current_url)

        html_text = fetch_url(session, current_url)
        if not html_text:
            continue

        title, text, soup = soup_text(html_text)
        career_verified, _, _ = is_probable_career_page(source_url, title, text)
        source_type = detect_source_type(current_url)

        # JSON-LD JobPosting.
        for item in extract_jsonld_jobs(html_text, current_url):
            job_url = normalize_url(item.get("url") or current_url)
            if not job_url or job_url in seen:
                continue
            score_data = score_against_profile(item.get("title", title), text)
            if score_data["score"] < min_score:
                continue
            item_title = item.get("title") or detect_title(title, text)
            item_location = item.get("location", "")[:120]
            item_contract = item.get("contract_type", "")
            item_published = item.get("published_at", "")
            ok_constraints, why_constraints = passes_job_constraints(
                item_title, text, item_location, item_contract, item_published,
                published_year, allow_unknown_published_date, allowed_country_terms,
            )
            if not ok_constraints:
                continue
            job = JobResult(
                url=job_url,
                source_url=source_url,
                company=company,
                title=item_title,
                location=item_location,
                contract_type=item_contract,
                published_at=item_published,
                found_at=datetime.now(timezone.utc).isoformat(),
                score=score_data["score"],
                mobilisation_time=score_data["mobilisation_time"],
                matched_skills=score_data["matched_skills"],
                missing_or_weak_keywords=score_data["missing_or_weak_keywords"],
                snippet=make_snippet(text),
                classification_confidence=0.98,
                classification_reason=f"JSON-LD JobPosting détecté. {why_constraints}".strip(),
                title_profile_matches=score_data.get("title_profile_matches", []),
                career_page_verified=career_verified,
                source_type=source_type,
            )
            seen.add(job.url)
            publish_job(job, out_path, csv_path)

        # Page actuelle = fiche individuelle potentielle.
        is_job, conf, reason = classify_job_page(current_url, title, text)
        if use_ai:
            ai_result = ai_classify_job_page(current_url, title, text)
            if ai_result:
                ai_is_job, ai_conf, ai_reason = ai_result
                # IA tranche seulement si confiance supérieure.
                if ai_conf >= conf:
                    is_job, conf, reason = ai_is_job, ai_conf, ai_reason

        if is_job and current_url not in seen:
            job_title = detect_title(title, text)
            score_data = score_against_profile(job_title, text)
            if score_data["score"] >= min_score:
                page_location = extract_location(text)
                page_contract = extract_contract_type(text)
                ok_constraints, why_constraints = passes_job_constraints(
                    job_title, text, page_location, page_contract, "",
                    published_year, allow_unknown_published_date, allowed_country_terms,
                )
                if not ok_constraints:
                    continue
                job = JobResult(
                    url=current_url,
                    source_url=source_url,
                    company=company,
                    title=job_title,
                    location=page_location,
                    contract_type=page_contract,
                    published_at="",
                    found_at=datetime.now(timezone.utc).isoformat(),
                    score=score_data["score"],
                    mobilisation_time=score_data["mobilisation_time"],
                    matched_skills=score_data["matched_skills"],
                    missing_or_weak_keywords=score_data["missing_or_weak_keywords"],
                    snippet=make_snippet(text),
                    classification_confidence=conf,
                    classification_reason=f"{reason} {why_constraints}".strip(),
                    title_profile_matches=score_data.get("title_profile_matches", []),
                    career_page_verified=career_verified,
                    source_type=source_type,
                )
                seen.add(job.url)
                publish_job(job, out_path, csv_path)

        # Ne suit les liens que jusqu'à max_depth.
        if depth >= max_depth:
            time.sleep(delay)
            continue

        # Ajoute uniquement les liens plausiblement liés au recrutement, sur même domaine ou ATS.
        for link in extract_links(current_url, html_text):
            if link in visited:
                continue
            if not same_domain_or_ats(source_url, link):
                continue

            link_l = link.lower()
            recruitment_hint = any(h in link_l for h in [
                "job", "career", "carriere", "carri", "emploi", "offre",
                "recruit", "position", "opening", "lever.co", "greenhouse",
                "workdayjobs", "workable", "smartrecruiters", "welcomekit",
                "linkedin", "indeed", "hellowork", ".pdf",
            ])
            if not recruitment_hint:
                continue

            # Pour profondeur > 0, on privilégie les URLs d'offres.
            if depth >= 0 and not (looks_like_job_url(link) or any(x in link_l for x in ["career", "jobs", "emploi", "offres"])):
                continue

            queue.append((link, depth + 1))

        time.sleep(delay)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Surveillance d'offres avec filtrage fiches postes + matching compétences.")
    p.add_argument("--input", "-i", type=Path, help="CSV ou TXT contenant les pages carrières à surveiller.")
    p.add_argument("--url", action="append", default=[], help="URL source à surveiller. Peut être répété.")
    p.add_argument("--out", type=Path, default=Path("jobs_found.jsonl"), help="Sortie JSONL incrémentale.")
    p.add_argument("--csv", type=Path, default=Path("jobs_found.csv"), help="Sortie CSV incrémentale. Utiliser --no-csv pour désactiver.")
    p.add_argument("--no-csv", action="store_true", help="Désactive la sortie CSV.")
    p.add_argument("--min-score", type=float, default=35.0, help="Score minimum d'adéquation au profil pour publier une offre.")
    p.add_argument("--max-depth", type=int, default=1, help="Profondeur de crawl depuis chaque page source.")
    p.add_argument("--max-pages", type=int, default=3, help="Pagination générique maximum à essayer par source.")
    p.add_argument("--delay", type=float, default=0.7, help="Pause entre requêtes pour éviter de surcharger les sites.")
    p.add_argument("--use-ai", action="store_true", help="Active la classification IA optionnelle si OPENAI_API_KEY est disponible.")
    p.add_argument("--include-marketplaces", action="store_true", help="Ajoute des recherches LinkedIn, Indeed et HelloWork à partir des intitulés ciblés.")
    p.add_argument("--marketplaces", nargs="+", default=["hellowork", "indeed", "linkedin"], help="Job boards à utiliser: hellowork indeed linkedin.")
    p.add_argument("--location", default="France", help="Localisation utilisée pour les recherches job boards.")
    p.add_argument("--role-query", action="append", default=[], help="Intitulé de poste supplémentaire à rechercher. Peut être répété.")
    p.add_argument("--published-year", type=int, default=2026, help="Année de publication acceptée. Par défaut: 2026. Utiliser 0 pour désactiver.")
    p.add_argument("--allow-unknown-published-date", action="store_true", help="Accepte les offres sans date de publication détectable malgré le filtre année.")
    p.add_argument("--country-term", action="append", default=[], help="Terme de localisation autorisé supplémentaire. Par défaut: France et Suisse.")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    if not args.input and not args.url and not args.include_marketplaces:
        print("Erreur: fournissez --input organisations.csv, au moins une --url, ou --include-marketplaces.", file=sys.stderr)
        return 2

    sources = read_sources(args.input, args.url)
    published_year = args.published_year or None
    allowed_country_terms = list(ALLOWED_COUNTRY_TERMS) + list(args.country_term or [])
    if args.include_marketplaces:
        role_queries = args.role_query or TARGET_ROLE_TITLES
        sources.extend(build_marketplace_sources(args.marketplaces, role_queries, args.location))
    if not sources:
        print("Aucune source valide trouvée.", file=sys.stderr)
        return 2

    csv_path = None if args.no_csv else args.csv
    seen = load_seen(args.out)
    session = requests.Session()

    print(f"🚀 Job Watch lancé — {len(sources)} source(s)")
    print(f"   Sortie JSONL : {args.out}")
    if csv_path:
        print(f"   Sortie CSV   : {csv_path}")
    print(f"   Score minimum: {args.min_score}")
    if published_year:
        print(f"   Filtre publication: {published_year} ({'date inconnue acceptée' if args.allow_unknown_published_date else 'date inconnue refusée'})")
    print("   Filtre localisation: France + Suisse")
    print("   Exclusions: stage/alternance/senior/responsable, >5 ans d'expérience, doctorat requis hors offres PhD")
    print("   Les offres validées sont publiées immédiatement.\n", flush=True)

    for company, source_url in sources:
        try:
            crawl_source(
                session=session,
                company=company,
                source_url=source_url,
                max_depth=args.max_depth,
                max_pages=args.max_pages,
                delay=args.delay,
                use_ai=args.use_ai,
                min_score=args.min_score,
                out_path=args.out,
                csv_path=csv_path,
                seen=seen,
                published_year=published_year,
                allow_unknown_published_date=args.allow_unknown_published_date,
                allowed_country_terms=allowed_country_terms,
            )
        except KeyboardInterrupt:
            print("\nArrêt demandé par l'utilisateur.", file=sys.stderr)
            return 130
        except Exception as exc:
            print(f"⚠️ Erreur source {source_url}: {exc}", file=sys.stderr)
            continue

    print("\n✅ Terminé.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

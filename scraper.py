import json, os, re
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

BASE = "https://www.nanshanlife.com.tw"
SOURCES = {
    "綜合商品": BASE + "/nanshanlife/popular-product/",
    "醫療保險": BASE + "/nanshanlife/products-health/",
    "長期照護保障": BASE + "/nanshanlife/products-long-term-care/",
    "人壽保險": BASE + "/nanshanlife/products-life-caring/",
    "意外保險": BASE + "/nanshanlife/products-accident/",
    "保障型商品": BASE + "/nanshanlife/features-protection/",
    "外溢保單": BASE + "/nanshanlife/features-spillover/",
    "小額終老": BASE + "/nanshanlife/features-basic/",
}
CATEGORIES = ["人壽保險", "醫療保險", "意外保險", "癌症／重大疾病保障", "長期照護保障", "其他"]
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OfficialProductCatalog/1.0)", "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"}

def clean(s):
    return re.sub(r"\\s+", " ", s or "").strip()

def classify(name, code, desc, source_cat):
    text = f"{name} {code} {desc}"
    cats = []
    rules = [
        ("癌症／重大疾病保障", r"癌症|重大疾病|重大傷病|特定傷病|精選傷病|特定疾病"),
        ("長期照護保障", r"長期照顧|長期照護|長照|失智照顧|失能照顧"),
        ("意外保險", r"意外|傷害|燒燙傷"),
        ("醫療保險", r"醫療|住院|手術|門診|健康保險"),
        ("人壽保險", r"壽險|終身壽險|定期壽險|身故|完全失能"),
    ]
    for category, pattern in rules:
        if re.search(pattern, text):
            cats.append(category)
    # Category landing pages are reliable classification hints, but never
    # suppress additional categories found in the actual product description.
    if source_cat in CATEGORIES and source_cat not in cats:
        cats.append(source_cat)
    return cats or ["其他"]

def get_card(anchor):
    node = anchor
    candidates = []
    for _ in range(10):
        if node is None:
            break
        text = clean(node.get_text(" ", strip=True))
        if "南山人壽" in text and len(text) < 6000 and re.search(r"商品DM|商品條款|投保須知|詳細內容", text):
            candidates.append((len(text), node, text))
        node = node.parent
    return min(candidates, key=lambda x: x[0])[1:] if candidates else None

def parse_name_code(text):
    # Official cards commonly place the code on a separate line after the name.
    match = re.search(r"(南山人壽.{2,160}?)\\s+([A-Z0-9]{2,12})\\s+(.{0,260}?)(?=承保年齡|繳費方式|繳費期間|幣別|商品DM|商品條款|投保須知)", text)
    if match and re.search(r"[A-Z]", match.group(2)):
        return clean(match.group(1)), match.group(2), clean(match.group(3))
    name = re.search(r"南山人壽[^\\n]{2,160}", text)
    if not name:
        return None
    title = clean(name.group(0))
    title = re.split(r"承保年齡|繳費方式|繳費期間|幣別", title)[0]
    return title, "", ""

def scrape():
    session = requests.Session()
    session.headers.update(HEADERS)
    products = {}
    errors = []
    for source_cat, url in SOURCES.items():
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
            response.encoding = response.apparent_encoding or "utf-8"
            soup = BeautifulSoup(response.text, "html.parser")
            seen_cards = set()
            for anchor in soup.find_all("a", href=True):
                result = get_card(anchor)
                if not result:
                    continue
                card, context = result
                parsed = parse_name_code(context)
                if not parsed:
                    continue
                name, code, description = parsed
                if not name.startswith("南山人壽") or len(name) > 160:
                    continue
                identity = code or re.sub(r"[^\\w]", "", name)
                if identity in seen_cards:
                    continue
                seen_cards.add(identity)
                categories = classify(name, code, description or context, source_cat)
                entry = products.setdefault(identity, {
                    "name": name, "code": code, "description": (description or context[:600]),
                    "categories": [], "source_url": url, "detail_url": None,
                    "dm_url": None, "terms_url": None, "status": "南山官方商品頁列示"
                })
                entry["categories"] = list(dict.fromkeys(entry["categories"] + categories))
                for link in card.find_all("a", href=True):
                    label = clean(link.get_text(" ", strip=True))
                    href = urljoin(url, link["href"])
                    if label == "商品DM":
                        entry["dm_url"] = href
                    elif label == "商品條款":
                        entry["terms_url"] = href
                    elif label == "投保須知":
                        entry["notice_url"] = href
                    elif label == "詳細內容":
                        entry["detail_url"] = href
        except Exception as exc:
            errors.append(f"{source_cat}: {type(exc).__name__}: {exc}")
    if not products:
        raise RuntimeError("未能從南山官方頁面辨識商品；保留既有資料，不發布空目錄。 " + " | ".join(errors))
    stamp = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    return {
        "products": sorted(products.values(), key=lambda p: (p["name"], p["code"])),
        "updated_at": stamp,
        "source_status": "已從南山人壽官方商品分類及特色商品頁擷取；非歷史停售商品全集。未符合五類者歸入其他；商品是否仍可投保以官方最新公告及條款為準。",
        "error": "；".join(errors) if errors else None
    }

def save_data(data):
    os.makedirs("data", exist_ok=True)
    temp = "data/products.tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(temp, "data/products.json")

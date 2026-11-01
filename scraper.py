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
}
CATEGORIES = ["人壽保險", "醫療保險", "意外保險", "癌症／重大疾病保障", "長期照護保障"]
DOC_LABELS = ("商品DM", "商品條款", "投保須知")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OfficialProductCatalog/1.0)", "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"}

def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()

def classify(name, code, desc, source_cat):
    text = f"{name} {code} {desc}"
    cats = [source_cat] if source_cat in CATEGORIES else []
    for cat, pattern in [
        ("癌症／重大疾病保障", r"癌症|重大疾病|重大傷病|特定傷病|精選傷病|特定疾病"),
        ("長期照護保障", r"長期照顧|長期照護|長照|失能照顧"),
        ("意外保險", r"意外|傷害"),
        ("醫療保險", r"醫療|住院|手術|健康保險"),
        ("人壽保險", r"壽險|終身壽險|定期壽險|身故"),
    ]:
        if re.search(pattern, text):
            cats.append(cat)
    return list(dict.fromkeys(cats))

def product_context(anchor):
    # Walk from the link upward and select the smallest block containing a
    # 南山人壽 product name, its uppercase product code and product metadata.
    node = anchor
    candidates = []
    for _ in range(9):
        if node is None:
            break
        text = clean(node.get_text(" ", strip=True))
        if "南山人壽" in text and re.search(r"\b(?=[A-Z0-9]{2,12}\b)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{2,12}\b", text) and re.search(r"承保年齡|繳費方式|繳費期間|商品DM|商品條款", text):
            candidates.append((len(text), node, text))
        node = node.parent
    if not candidates:
        return None
    return min(candidates, key=lambda x: x[0])[1:]

def scrape():
    session = requests.Session()
    session.headers.update(HEADERS)
    products = {}
    errors = []
    for source_cat, url in SOURCES.items():
        try:
            response = session.get(url, timeout=25)
            response.raise_for_status()
            response.encoding = response.apparent_encoding or "utf-8"
            soup = BeautifulSoup(response.text, "html.parser")
            found = 0
            for anchor in soup.find_all("a", href=True):
                result = product_context(anchor)
                if not result:
                    continue
                card, context = result
                name_match = re.search(r"南山人壽.{2,130}?(?=承保年齡|繳費方式|繳費期間|幣別)", context)
                if not name_match:
                    continue
                raw_product = clean(name_match.group(0))
                # Product code is the first standalone alphanumeric token after
                # the Chinese product name; require at least one Latin letter.
                code_match = re.search(r"\\s([A-Z0-9]{2,12})\\s", raw_product)
                if not code_match or not re.search(r"[A-Z]", code_match.group(1)):
                    continue
                code = code_match.group(1)
                name = clean(raw_product[:code_match.start(1)])
                summary = clean(raw_product[code_match.end(1):])
                if len(name) > 100 or not name.startswith("南山人壽"):
                    continue
                categories = classify(name, code, summary, source_cat)
                if not categories:
                    continue
                key = code
                entry = products.setdefault(key, {
                    "name": name, "code": code, "description": summary,
                    "categories": [], "source_url": url, "detail_url": None,
                    "dm_url": None, "terms_url": None, "status": "南山官方精選商品頁列示"
                })
                entry["categories"] = list(dict.fromkeys(entry["categories"] + categories))
                found += 1
                for link in card.find_all("a", href=True):
                    label = clean(link.get_text(" ", strip=True))
                    href = urljoin(url, link["href"])
                    if label == "商品DM":
                        entry["dm_url"] = href
                    elif label == "商品條款":
                        entry["terms_url"] = href
                    elif label == "詳細內容":
                        entry["detail_url"] = href
                found += 1
            if found == 0:
                errors.append(f"{source_cat}: 頁面可讀取，但沒有辨識到具商品代碼及欄位的商品卡")
        except Exception as exc:
            errors.append(f"{source_cat}: {type(exc).__name__}: {exc}")
    if not products:
        raise RuntimeError("未能從南山官方頁面辨識商品；保留既有資料，不發布空目錄。 " + " | ".join(errors))
    stamp = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    return {
        "products": sorted(products.values(), key=lambda p: (p["name"], p["code"])),
        "updated_at": stamp,
        "source_status": "已從南山人壽官方精選熱門商品頁擷取（非全商品清單）；商品是否仍可投保以官方最新公告及條款為準。分類為關鍵字輔助整理。",
        "error": "；".join(errors) if errors else None
    }

def save_data(data):
    os.makedirs("data", exist_ok=True)
    temp = "data/products.tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(temp, "data/products.json")

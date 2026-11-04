import json, os, re, unicodedata
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
    "旅行險": BASE + "/nanshanlife/products-travel/",
    "團體保險": BASE + "/nanshanlife/products-group-insurance/",
    "投資型商品": BASE + "/nanshanlife/features-investment/",
    "網路投保商品": BASE + "/nanshanlife/products-selling-online/",
    "銀行保險商品": BASE + "/nanshanlife/products-selling-bank/",
    "還本增額年金": BASE + "/nanshanlife/products-savings-refund/",
}
CATEGORIES = ["人壽保險", "醫療保險", "意外保險", "癌症／重大疾病保障", "長期照護保障", "其他"]
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OfficialProductCatalog/1.0)", "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"}

def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()

def normalize_name(s):
    value = unicodedata.normalize("NFKC", clean(s)).casefold()
    return "".join(ch for ch in value if ch.isalnum())

def classify(name, code, desc, source_cat):
    text = f"{name} {code} {desc}"
    cats = []
    rules = [
        ("癌症／重大疾病保障", r"癌症|癌|重大疾病|重大傷病|特定傷病|精選傷病|特定疾病"),
        ("長期照護保障", r"長期照顧|長期照護|長照|失智|失能照顧"),
        ("意外保險", r"意外|傷害|燒燙傷"),
        ("醫療保險", r"醫療|住院|手術|門診|病房|醫療費"),
        ("人壽保險", r"壽險|終身壽險|定期壽險|身故|壽險保障"),
    ]
    for category, pattern in rules:
        if re.search(pattern, text):
            cats.append(category)
    if source_cat in CATEGORIES[:-1] and source_cat not in cats:
        cats.append(source_cat)
    return cats or ["其他"]

def parse_products_from_page(soup, source_cat, url, products):
    lines = [clean(x) for x in soup.get_text("\n").splitlines()]
    lines = [x for x in lines if x]
    for i, line in enumerate(lines):
        if not line.startswith("南山人壽"):
            continue
        # Avoid navigation, page headings, and long paragraphs masquerading as names.
        if len(line) > 160 or any(x in line for x in ("客服", "商品一覽", "商品列表", "南山人壽總公司", "南山人壽APP", "慈善基金會", "提供多項", "和您一起", "全方位守護")):
            continue
        if not re.search(r"保險|附約|附加條款|健康|壽險|年金|傷害|長期照顧|醫療", line):
            continue
        name = line
        code = ""
        summary = ""
        for nxt in lines[i+1:i+5]:
            if re.fullmatch(r"(?=[A-Z0-9 -]{2,24}$)(?=.*[A-Z])(?=.*[0-9])[A-Z0-9 -]+", nxt):
                code = nxt
                continue
            if any(k in nxt for k in ("承保年齡", "繳費方式", "繳費期間", "幣別", "商品DM", "商品條款")):
                break
            if not summary and len(nxt) < 240:
                summary = nxt
        identity = normalize_name(name)
        cats = classify(name, code, summary, source_cat)
        entry = products.setdefault(identity, {
            "name": name, "code": code, "description": summary,
            "categories": [], "source_url": url, "detail_url": None,
            "dm_url": None, "terms_url": None, "notice_url": None,
            "status": "南山官方商品頁列示"
        })
        entry["categories"] = list(dict.fromkeys((entry.get("categories") or []) + cats))
        # Refresh fields only when the official page supplies a non-empty value.
        if summary:
            entry["description"] = summary
        if code:
            entry["code"] = code
        entry["name"] = name
        entry["source_url"] = url or entry.get("source_url", "")
    # Attach document links to the smallest ancestor block containing one
    # identifiable product name. Do not borrow links from a whole page section.
    for a in soup.find_all("a", href=True):
        label = clean(a.get_text(" ", strip=True))
        if label not in ("商品DM", "商品條款", "投保須知", "詳細內容"):
            continue
        node = a
        chosen = None
        for _ in range(10):
            if node is None:
                break
            text = clean(node.get_text(" ", strip=True))
            matches = [p for p in products.values() if p["name"] in text]
            if len(matches) == 1 and len(text) < 5000:
                chosen = matches[0]
                break
            node = node.parent
        if chosen:
            href = urljoin(url, a["href"])
            key = {"商品DM":"dm_url", "商品條款":"terms_url", "投保須知":"notice_url", "詳細內容":"detail_url"}[label]
            chosen[key] = href

def load_existing_products():
    """Seed each refresh with the last verified catalogue so a partial source read cannot erase records."""
    path = "data/products.json"
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        result = {}
        for item in saved.get("products", []):
            name = clean(item.get("name"))
            code = clean(item.get("code"))
            if not name:
                continue
            identity = normalize_name(name)
            item.setdefault("categories", ["其他"])
            item.setdefault("description", "")
            item.setdefault("source_url", "")
            for key in ("detail_url", "dm_url", "terms_url", "notice_url"):
                item.setdefault(key, None)
            if identity in result:
                current = result[identity]
                current["categories"] = list(dict.fromkeys((current.get("categories") or []) + (item.get("categories") or [])))
                for field in ("code", "description", "source_url", "detail_url", "dm_url", "terms_url", "notice_url"):
                    if not current.get(field) and item.get(field):
                        current[field] = item[field]
            else:
                result[identity] = item
        return result
    except Exception as exc:
        # Do not silently replace a catalogue that could not be read.
        raise RuntimeError(f"無法讀取既有商品目錄，停止更新以避免資料遺失: {exc}") from exc

def scrape():
    session = requests.Session()
    session.headers.update(HEADERS)
    products = load_existing_products()
    existing_count = len(products)
    errors = []
    browser = None
    page = None
    playwright = None
    try:
        from playwright.sync_api import sync_playwright
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(locale="zh-TW")
    except Exception as exc:
        errors.append(f"瀏覽器初始化失敗: {type(exc).__name__}: {exc}")

    for source_cat, url in SOURCES.items():
        before = len(products)
        try:
            response = session.get(url, timeout=25)
            response.raise_for_status()
            response.encoding = response.apparent_encoding or "utf-8"
            parse_products_from_page(BeautifulSoup(response.text, "html.parser"), source_cat, url, products)
        except Exception as exc:
            errors.append(f"{source_cat} HTML: {type(exc).__name__}: {exc}")

        # Always parse the rendered page as well: official product cards and
        # their DM/terms/detail links may be injected by client-side scripts,
        # even when the static HTML already contains product names.
        if page is not None:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3500)
                parse_products_from_page(BeautifulSoup(page.content(), "html.parser"), source_cat, url, products)
            except Exception as exc:
                errors.append(f"{source_cat} 瀏覽器: {type(exc).__name__}: {exc}")
        if len(products) == before:
            errors.append(f"{source_cat}: 頁面可讀取，但未辨識到商品名稱")

    if browser is not None:
        browser.close()
    if playwright is not None:
        playwright.stop()
    if not products:
        raise RuntimeError("未能從南山官方頁面辨識商品；保留既有資料，不發布空目錄。 " + " | ".join(errors))
    if len(products) < existing_count:
        raise RuntimeError(f"安全檢查失敗：更新後商品數 {len(products)} 少於既有 {existing_count}；停止發布。")
    # Final canonical deduplication: names can arrive with invisible Unicode
    # spacing/punctuation differences and some official pages omit product codes.
    deduplicated = {}
    for item in products.values():
        name_key = normalize_name(item.get("name", ""))
        code_key = clean(item.get("code", "")).casefold()
        identity = ("name:" + name_key) if name_key else ("code:" + code_key)
        if not name_key:
            continue
        if identity not in deduplicated:
            deduplicated[identity] = item
            continue
        current = deduplicated[identity]
        current["categories"] = list(dict.fromkeys((current.get("categories") or []) + (item.get("categories") or [])))
        for field in ("description", "source_url", "detail_url", "dm_url", "terms_url", "notice_url", "code"):
            if not current.get(field) and item.get(field):
                current[field] = item[field]
    products = deduplicated
    stamp = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    return {
        "products": sorted(products.values(), key=lambda p: (p["name"], p["code"])),
        "updated_at": stamp,
        "source_status": "已從南山人壽官方商品分類及特色商品頁擷取；未符合指定保障類別者歸入其他。此目錄以官方目前公開商品頁為範圍，不等同歷史停售商品全集；銷售狀態以官方最新公告及條款為準。",
        "error": "；".join(errors) if errors else None
    }

def save_data(data):
    os.makedirs("data", exist_ok=True)
    temp = "data/products.tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(temp, "data/products.json")

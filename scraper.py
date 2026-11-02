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
            if re.fullmatch(r"(?=[A-Z0-9]{2,12}$)(?=.*[A-Z])[A-Z0-9]+", nxt):
                code = nxt
                continue
            if any(k in nxt for k in ("承保年齡", "繳費方式", "繳費期間", "幣別", "商品DM", "商品條款")):
                break
            if not summary and len(nxt) < 240:
                summary = nxt
        identity = code or re.sub(r"[^\\w]", "", name)
        cats = classify(name, code, summary, source_cat)
        entry = products.setdefault(identity, {
            "name": name, "code": code, "description": summary,
            "categories": [], "source_url": url, "detail_url": None,
            "dm_url": None, "terms_url": None, "notice_url": None,
            "status": "南山官方商品頁列示"
        })
        entry["categories"] = list(dict.fromkeys(entry["categories"] + cats))
        if summary and not entry.get("description"):
            entry["description"] = summary
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

def scrape():
    session = requests.Session()
    session.headers.update(HEADERS)
    products = {}
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

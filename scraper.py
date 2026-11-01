import json, os, re
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

BASE = "https://www.nanshanlife.com.tw"
# These are official category pages linked from the insurer's product directory.
SOURCES = {
    "醫療保險": BASE + "/nanshanlife/products-health/",
    "長期照護保障": BASE + "/nanshanlife/products-long-term-care/",
    "人壽保險": BASE + "/nanshanlife/products-life-caring/",
    "意外保險": BASE + "/nanshanlife/products-accident/",
}
CATEGORIES = ["人壽保險", "醫療保險", "意外保險", "癌症／重大疾病保障", "長期照護保障"]
DOC_LABELS = ("商品DM", "商品條款", "投保須知")

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

def scrape():
    products = {}
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(locale="zh-TW")
        page.set_default_navigation_timeout(30000)
        page.set_default_timeout(10000)
        page.set_extra_http_headers({"Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"})
        for source_cat, url in SOURCES.items():
            try:
                # Avoid networkidle: analytics requests may remain open indefinitely.
                response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                if response and response.status >= 400:
                    raise RuntimeError(f"HTTP {response.status}")
                # Allow client-rendered product cards a short, bounded hydration window.
                page.wait_for_timeout(1200)
                try:
                    page.locator("body").wait_for(state="visible", timeout=5000)
                except Exception:
                    pass
                # Product cards contain the insurer's product name and official code.
                cards = page.locator("body").inner_text()
                anchors = page.locator("a").evaluate_all("""els => els.map(a => ({
                    label:(a.innerText||a.textContent||'').trim(),
                    href:a.href,
                    context:(a.closest('article, li, .product-card, .card, [class*=product]')?.innerText ||
                            a.parentElement?.parentElement?.innerText || '').trim()
                }))""")
                found_on_page = 0
                for a in anchors:
                    context = clean(a["context"])
                    label = clean(a["label"])
                    if not context or "南山人壽" not in context:
                        continue
                    name_match = re.search(r"南山人壽.{2,90}?(?=(?:[A-Z0-9]{2,12})?\s*(?:承保年齡|繳費方式|繳費期間|幣別|商品DM|商品條款|$))", context)
                    if not name_match:
                        name_match = re.search(r"南山人壽[^。；\n]{2,80}", context)
                    if not name_match:
                        continue
                    name = clean(name_match.group(0))
                    code_match = re.search(r"\b[A-Z][A-Z0-9]{1,11}\b", context)
                    code = code_match.group(0) if code_match else ""
                    # Ignore navigation or non-product text.
                    if len(name) > 95 or any(x in name for x in ["熱門商品推薦", "商品一覽", "商品列表"]):
                        continue
                    if not re.search(r"商品DM|商品條款|承保年齡|繳費期間|繳費方式|幣別", context):
                        continue
                    key = code or name
                    entry = products.setdefault(key, {
                        "name": name, "code": code, "description": context[:700],
                        "categories": [], "source_url": url, "detail_url": None,
                        "dm_url": None, "terms_url": None, "status": "官方分類頁列示"
                    })
                    entry["categories"] = list(dict.fromkeys(entry["categories"] + classify(name, code, context, source_cat)))
                    if a["href"].startswith(BASE) and a["href"] != url:
                        if not entry["detail_url"] and label not in DOC_LABELS:
                            entry["detail_url"] = a["href"]
                    found_on_page += 1
                # Documents are attached only when their link is within the same product card.
                for a in anchors:
                    context = clean(a["context"])
                    if "南山人壽" not in context:
                        continue
                    nm = re.search(r"南山人壽[^。；\n]{2,80}", context)
                    if not nm: continue
                    cm = re.search(r"\b[A-Z][A-Z0-9]{1,11}\b", context)
                    key = cm.group(0) if cm else clean(nm.group(0))
                    if key not in products: continue
                    label, href = clean(a["label"]), a["href"]
                    if not href.startswith("http"): continue
                    if "商品DM" in label: products[key]["dm_url"] = href
                    if "商品條款" in label: products[key]["terms_url"] = href
                if found_on_page == 0:
                    errors.append(f"{source_cat}: 官方頁面有載入，但未辨識到符合商品卡欄位的資料")
            except Exception as e:
                errors.append(f"{source_cat}: {type(e).__name__}: {e}")
        browser.close()
    if not products:
        raise RuntimeError("未能從官方分類頁辨識商品卡；不更新資料，以免發布不實內容。 " + " | ".join(errors))
    stamp = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    return {
        "products": list(products.values()), "updated_at": stamp,
        "source_status": "已擷取官方分類頁商品卡；分類為關鍵字輔助整理，請以官方條款為準",
        "error": "；".join(errors) if errors else None
    }

def save_data(data):
    os.makedirs("data", exist_ok=True)
    temp = "data/products.tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(temp, "data/products.json")

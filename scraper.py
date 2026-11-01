import json, os, re
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

BASE = 'https://www.nanshanlife.com.tw'
SOURCES = {
 '醫療保險': '/nanshanlife/products-health/products-health',
 '長期照護保障': '/nanshanlife/products-health/products-long-term-care',
 '人壽保險': '/nanshanlife/products-health/products-life-caring',
 '意外保險': '/nanshanlife/products-health/products-accident',
}
CATEGORIES = ['人壽保險','醫療保險','意外保險','癌症／重大疾病保障','長期照護保障']

def classify(name, code, desc, source_cat):
    text = f'{name} {code} {desc}'
    cats = [source_cat] if source_cat in CATEGORIES else []
    rules = [
      ('癌症／重大疾病保障', r'癌症|重大疾病|重大傷病|特定傷病|精選傷病|特定疾病'),
      ('長期照護保障', r'長期照顧|長期照護|長照|失能照顧'),
      ('意外保險', r'意外|傷害'),
      ('醫療保險', r'醫療|住院|手術|健康保險'),
      ('人壽保險', r'壽險|終身壽險|定期壽險|身故'),
    ]
    for cat, pattern in rules:
      if re.search(pattern, text): cats.append(cat)
    return list(dict.fromkeys(cats)) or ([source_cat] if source_cat in CATEGORIES else [])

def scrape():
    products = {}
    errors = []
    with sync_playwright() as p:
      browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
      page = browser.new_page(locale='zh-TW')
      for source_cat, path in SOURCES.items():
        url = urljoin(BASE, path)
        try:
          page.goto(url, wait_until='domcontentloaded', timeout=60000)
          page.wait_for_timeout(4500)
          cards = page.locator('a').evaluate_all("els => els.map(a => ({text:(a.innerText||a.textContent||'').trim(), href:a.href, parent:(a.parentElement?.parentElement?.innerText||'').trim()}))")
          for item in cards:
            text = re.sub(r'\\s+', ' ', item['text']).strip()
            parent = re.sub(r'\\s+', ' ', item['parent']).strip()
            if not text or not item['href'].startswith(BASE): continue
            if any(x in text for x in ['商品DM','商品條款','投保須知','詳細內容']): continue
            code_match = re.search(r'\\b[A-Z][A-Z0-9]{1,9}\\b', parent)
            name_match = re.search(r'南山人壽[^\\n]{3,70}', parent)
            if not name_match: continue
            name = name_match.group(0).strip()
            code = code_match.group(0) if code_match else ''
            if len(name) > 90: continue
            desc = parent[:500]
            key = code or name
            entry = products.setdefault(key, {'name':name,'code':code,'description':desc,'categories':[],'source_url':url,'detail_url':item['href'],'dm_url':None,'terms_url':None})
            entry['categories'] = list(dict.fromkeys(entry['categories'] + classify(name, code, desc, source_cat)))
            # Collect nearby official document links where available.
            for a in page.locator('a').all():
              try:
                label = (a.inner_text() or '').strip()
                href = a.get_attribute('href')
                if href and any(k in label for k in ['商品DM','商品條款']):
                  if 'DM' in label: entry['dm_url'] = urljoin(BASE, href)
                  if '條款' in label: entry['terms_url'] = urljoin(BASE, href)
              except Exception: pass
        except Exception as e:
          errors.append(f'{source_cat}: {type(e).__name__}: {e}')
      browser.close()
    if not products:
      raise RuntimeError('官方商品頁未取得可辨識商品；為避免錯誤資料，不更新現有清單。 ' + ' | '.join(errors))
    stamp = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')
    return {'products':list(products.values()),'updated_at':stamp,'source_status':'已同步官方商品頁（分類為自動整理，請以官方文件為準）','error':'；'.join(errors) if errors else None}

def save_data(data):
    os.makedirs('data', exist_ok=True)
    temp='data/products.tmp'
    with open(temp,'w',encoding='utf-8') as f: json.dump(data,f,ensure_ascii=False,indent=2)
    os.replace(temp,'data/products.json')

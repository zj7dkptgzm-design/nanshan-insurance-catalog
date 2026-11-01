import json, os
from flask import Flask, render_template, request

app = Flask(__name__)
DATA = "data/products.json"

def load_data():
    try:
        with open(DATA, encoding="utf-8") as f: return json.load(f)
    except Exception:
        return {"products": [], "updated_at": None, "source_status": "尚未同步", "error": None}

@app.get("/")
def home():
    data = load_data()
    q = request.args.get("q", "").strip().lower()
    cat = request.args.get("category", "").strip()
    products = data.get("products", [])
    if cat: products = [p for p in products if cat in p.get("categories", [])]
    if q:
        products = [p for p in products if q in " ".join([p.get("name",""),p.get("code",""),p.get("description","")]).lower()]
    return render_template("index.html", data=data, products=products, q=request.args.get("q",""), category=cat)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

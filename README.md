# 南山人壽商品查找

網站提供南山人壽官方「精選熱門商品」頁面中可核對的保障型商品查找，支援商品名稱、代碼、保障描述搜尋，以及五類保障標籤。單一商品可同時歸入多個保障類別。

**資料範圍限制：**目前自動同步來源是官方精選熱門商品頁，不代表南山人壽全部在售商品。官方醫療、長照、壽險及意外分類頁若未提供可讀取的商品卡，不會自行補造商品。特定分類沒有資料時，不代表該公司沒有該類商品。

## 官方資料來源

- 精選熱門商品：https://www.nanshanlife.com.tw/nanshanlife/popular-product/
- 醫療保險：https://www.nanshanlife.com.tw/nanshanlife/products-health/
- 長期照護：https://www.nanshanlife.com.tw/nanshanlife/products-long-term-care/
- 人壽保險：https://www.nanshanlife.com.tw/nanshanlife/products-life-caring/
- 意外保險：https://www.nanshanlife.com.tw/nanshanlife/products-accident/

商品卡若有官方商品DM、商品條款及詳細內容連結，會直接連到南山人壽網站。商品是否仍可投保，仍須以南山人壽最新公告、條款及實際核保規則為準。

## 資料更新

GitHub Actions 每日自動讀取官方頁面並更新目錄。若官方來源讀取失敗或無法辨識商品，流程會失敗並保留既有資料，不會以空清單或猜測資料覆蓋。

## 部署

Render 使用 Python / Flask 提供搜尋頁面。網站不收集客戶個人資料、不提供投保建議，也不是南山人壽官方網站。

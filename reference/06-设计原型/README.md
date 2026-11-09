# 06 · 设计原型

## 内容

5 版 UI 风格原型（Linear / Figma / Runway / Notion / Pinterest）+ 三套设计 token。

## 为什么这里没有文件

**原型不在这里，唯一真源是：**

```
docs/archive/ui-versions/
├─ index.html          5 版总览入口（也是 verify_index_linear.mjs 实测的页面）
├─ v1-linear.html      Linear 风格（最终被采纳，落地成 frontend/src/assets/styles.css）
├─ v2-figma.html
├─ v3-runway.html
├─ v4-notion.html
├─ v5-pinterest.html
├─ DESIGN.md           设计系统说明（亮度阶梯 / 半透明边框 / 间距）
└─ design-tokens/      5 套 token（figma / linear.app / notion / pinterest / runwayml 的 DESIGN.md）
```

## 为什么不复制一份过来

`tools/verify_index_linear.mjs` 直接打开 `docs/archive/ui-versions/index.html` 做 18 项视觉实测。
如果这里再放一份副本，改了一处忘了另一处，校验就会「测的是旧版、界面是新版」，属自欺欺人。
所以：**改原型去 `docs/archive/ui-versions/`，别在这里建副本。**

## 怎么看

```bash
# 直接浏览器打开总览
start docs/archive/ui-versions/index.html

# 或者跑视觉核验（会留截图到 screenshots/）
node tools/verify_index_linear.mjs
```

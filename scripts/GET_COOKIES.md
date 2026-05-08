# 如何导出小红书 Cookie

由于 Cookie 会过期，如果脚本提示"找不到上传按钮"或"页面加载失败"，说明 Cookie 需要重新导出。

## 🔄 重新导出 Cookie（5 分钟）

### 方法 1：浏览器 DevTools（推荐）

1. **打开浏览器**，进入 https://www.xiaohongshu.com
2. **点击登录**，用你的小红书账号登录
3. 登录成功后，按 **F12** 打开开发者工具（DevTools）
4. 选择 **Application** 标签（有些浏览器叫 Storage）
5. 左侧菜单找 **Cookies** → 选择 **https://www.xiaohongshu.com**
6. **全选所有 Cookie**
   - Windows/Linux：`Ctrl+A` 
   - Mac：`Cmd+A`
7. **复制**（右键 → Copy）
8. 打开文本编辑器，**粘贴** Cookie 内容
9. **保存为** `scripts/xhs_cookies.json`

### 方法 2：浏览器扩展（更简单）

1. 安装 **EditThisCookie** 扩展
   - Chrome: https://chrome.google.com/webstore/
   - 搜索 "EditThisCookie"

2. 打开小红书（https://www.xiaohongshu.com）并确保已登录

3. 点击扩展图标 → **Export** → 自动复制 JSON

4. 粘贴到 `scripts/xhs_cookies.json`

## ✅ 验证 Cookie 是否有效

```bash
node -e "
const fs = require('fs');
const c = JSON.parse(fs.readFileSync('./scripts/xhs_cookies.json'));
console.log('✅ Cookie 数量:', c.length);
console.log('   主要 Cookie:');
c.slice(0, 3).forEach(x => console.log('   -', x.name));
"
```

输出应该显示 10+ 个 Cookie。

## 🚀 导出完成后

重新运行脚本：

```bash
node scripts/save_draft.js
```

## ⚠️ 常见问题

**Q: Cookie 什么时候会过期？**
A: 通常几周到几个月。如果脚本 > 1 周没用，建议重新导出。

**Q: Cookie 包含我的密码吗？**
A: 不包含。Cookie 是登录凭证，但不是密码。

**Q: 可以分享 Cookie 文件吗？**
A: 不建议。Cookie 相当于"已登录状态"，其他人用你的 Cookie 可以以你的身份发布内容。

**Q: 如何删除本地 Cookie？**
A: 只需删除 `scripts/xhs_cookies.json` 文件即可。

---

**导出完成？运行试试：**

```bash
node scripts/save_draft.js
```

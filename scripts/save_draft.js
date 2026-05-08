/**
 * 小红书草稿保存脚本
 * 使用 Playwright 自动登录并将内容保存为草稿（不发布）
 *
 * 使用前请先导出 Cookie 到 xhs_cookies.json
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const content = require('./xhs_content');

const COOKIES_FILE = path.join(__dirname, 'xhs_cookies.json');
const IMAGES_DIR = path.join(__dirname, 'xhs_images');

async function typeSlowly(element, text, delay = 50) {
  for (const char of text) {
    await element.type(char);
    await element.page().waitForTimeout(delay);
  }
}

async function saveDraft() {
  // 检查必要文件
  if (!fs.existsSync(COOKIES_FILE)) {
    console.error('❌ 未找到 xhs_cookies.json，请先导出登录态 Cookie');
    console.log('   1. 浏览器登录 https://www.xiaohongshu.com');
    console.log('   2. DevTools → Application → Cookies');
    console.log('   3. 复制或导出为 JSON 格式，保存为 ./xhs_cookies.json');
    process.exit(1);
  }

  if (!fs.existsSync(IMAGES_DIR) || fs.readdirSync(IMAGES_DIR).length === 0) {
    console.error('❌ 未找到处理后的图片，请先运行 process_images.js');
    process.exit(1);
  }

  const images = fs.readdirSync(IMAGES_DIR)
    .filter(f => f.endsWith('.png'))
    .sort()
    .map(f => path.join(IMAGES_DIR, f));

  console.log(`📸 找到 ${images.length} 张图片`);
  images.forEach((img, i) => console.log(`   ${i+1}. ${path.basename(img)}`));

  let browser;
  try {
    // 读取 Cookie
    const cookies = JSON.parse(fs.readFileSync(COOKIES_FILE, 'utf-8'));
    console.log(`🔑 已读取 ${cookies.length} 个 Cookie`);

    // 启动浏览器
    browser = await chromium.launch({ headless: false });
    const context = await browser.newContext();
    await context.addCookies(cookies);
    const page = await context.newPage();

    console.log('\n🌐 打开小红书创作中心...');
    await page.goto('https://creator.xiaohongshu.com/publish/publish');
    await page.waitForLoadState('networkidle', { timeout: 10000 });

    // 等待上传按钮出现
    console.log('⏳ 等待发布页面加载...');
    await page.waitForSelector('[class*="upload"], input[type="file"], button[class*="upload"]', { timeout: 10000 });

    // 上传图片
    let uploadInput = await page.$('input[type="file"]');
    if (!uploadInput) {
      const inputs = await page.$$('input[type="file"]');
      if (inputs.length > 0) uploadInput = inputs[0];
    }

    if (uploadInput) {
      console.log('\n📤 上传图片...');
      for (let i = 0; i < images.length; i++) {
        await uploadInput.setInputFiles(images[i]);
        await page.waitForTimeout(2000);
        console.log(`   ✅ 已上传第 ${i+1}/${images.length} 张图片`);
      }
    } else {
      console.warn('⚠️  未找到图片上传输入框');
    }

    // 等待输入框出现
    await page.waitForTimeout(2000);

    // 填写标题
    console.log('\n📝 填写标题...');
    let titleInput = await page.$('input[placeholder*="title"]') ||
                     await page.$('input[placeholder*="标题"]') ||
                     await page.$('input[placeholder*="发布标题"]') ||
                     await page.$('textarea[placeholder*="标题"]');

    if (!titleInput) {
      const inputs = await page.$$('input');
      if (inputs.length > 0) titleInput = inputs[0];
    }

    if (titleInput) {
      await titleInput.click();
      await titleInput.fill('');
      await typeSlowly(titleInput, content.title, 30);
      console.log(`   ✅ 标题: ${content.title.slice(0, 30)}...`);
    }

    // 填写正文
    console.log('\n💬 填写正文...');
    let contentInput = await page.$('textarea[placeholder*="说说你想分享"]') ||
                       await page.$('textarea[placeholder*="正文"]') ||
                       await page.$('div[contenteditable="true"]');

    if (!contentInput) {
      const textareas = await page.$$('textarea');
      if (textareas.length > 0) contentInput = textareas[0];
    }

    if (contentInput) {
      const role = await contentInput.getAttribute('role');
      if (role === 'textbox' || contentInput.evaluate(el => el.getAttribute('contenteditable') === 'true')) {
        await contentInput.click();
        await contentInput.evaluate(el => el.textContent = '');
        await typeSlowly(contentInput, content.content, 10);
      } else {
        await contentInput.click();
        await contentInput.fill('');
        await typeSlowly(contentInput, content.content, 10);
      }
      console.log(`   ✅ 已填写正文 (${content.content.length} 字符)`);
    }

    // 添加话题标签
    console.log('\n🏷️  添加话题标签...');
    let tagInput = await page.$('input[placeholder*="话题"]') ||
                   await page.$('input[placeholder*="标签"]');

    if (tagInput && content.hashtags.length > 0) {
      for (const tag of content.hashtags.slice(0, 5)) {
        await tagInput.click();
        await tagInput.fill(`#${tag}`);
        await page.waitForTimeout(500);
        await page.keyboard.press('Enter');
        await page.waitForTimeout(300);
      }
      console.log(`   ✅ 已添加 ${Math.min(content.hashtags.length, 5)} 个话题`);
    }

    console.log('\n⏳ 正在保存草稿...');

    // 查找保存草稿按钮
    let savedSuccess = false;

    const saveDraftButtons = await page.$$('button');
    for (const btn of saveDraftButtons) {
      const text = await btn.textContent();
      if (text && (text.includes('保存草稿') || text.includes('保存'))) {
        console.log(`   🔍 找到保存按钮: "${text}"`);
        await btn.click();
        await page.waitForTimeout(2000);
        savedSuccess = true;
        break;
      }
    }

    if (!savedSuccess) {
      // 备选：尝试快捷键
      console.log('   尝试使用快捷键 Ctrl+S 保存...');
      await page.keyboard.press('Control+S');
      await page.waitForTimeout(2000);
    }

    console.log('\n✨ 草稿已保存！');
    console.log('📌 下一步：');
    console.log('   1. 在小红书创作中心查看并编辑草稿');
    console.log('   2. 预览图片、文案、话题是否正确');
    console.log('   3. 满意后点击"发布"按钮发布');
    console.log('   4. 或继续运行 publish_xhs.js 直接发布');

    console.log('\n💾 浏览器保持打开，方便你继续编辑...');
    console.log('   按 Ctrl+C 退出\n');

  } catch (error) {
    console.error('❌ 保存失败:', error.message);
    if (error.message.includes('Timeout')) {
      console.log('\n💡 可能原因：');
      console.log('   - 网络连接不稳定');
      console.log('   - Cookie 已过期，请重新导出');
      console.log('   - 小红书网页布局变化');
    }
    process.exit(1);
  }
}

saveDraft();

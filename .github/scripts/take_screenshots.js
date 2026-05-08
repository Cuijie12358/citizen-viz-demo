const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE_URL = process.env.BASE_URL || 'https://citizen-predict.vercel.app';

async function takeScreenshots() {
  console.log(`📸 Taking screenshots from ${BASE_URL}...`);

  // 创建目录
  const imagesDir = path.join(__dirname, '../../docs/images');
  fs.mkdirSync(imagesDir, { recursive: true });

  let browser;
  try {
    browser = await chromium.launch();
    const page = await browser.newPage();

    // 设置合适的视口大小
    await page.setViewportSize({ width: 1440, height: 900 });

    console.log('⏳ Loading application...');
    await page.goto(BASE_URL, {
      waitUntil: 'networkidle',
      timeout: 60000
    });

    // 等待主要内容加载和数据渲染
    await page.waitForTimeout(5000);

    // 等待 canvas 元素出现（Chart.js 使用 canvas 渲染图表）
    try {
      await page.waitForSelector('canvas', { timeout: 15000 });
    } catch (e) {
      console.warn('⚠️  Canvas elements not found, continuing anyway...');
    }

    // 截图 1: 数据仪表盘 (数据可视化)
    console.log('📷 Capturing visualization dashboard...');
    try {
      // 确保在 dashboard tab
      await page.click('button[data-view="dashboard"]');
      await page.waitForTimeout(3000);

      // 截图图表部分（不包含表格）
      const chartElement = await page.$('.charts-grid');
      if (chartElement) {
        await chartElement.screenshot({ path: path.join(imagesDir, 'visualization.png') });
      } else {
        // 如果找不到特定元素，就截整个页面
        await page.screenshot({ path: path.join(imagesDir, 'visualization.png') });
      }
      console.log('✅ visualization.png saved');
    } catch (e) {
      console.error('❌ Error capturing visualization:', e.message);
    }

    // 截图 2: 预测工具
    console.log('📷 Capturing predictor...');
    try {
      await page.click('button[data-view="predict"]');
      await page.waitForTimeout(3000);

      // 等待预测表单加载
      await page.waitForSelector('.prediction-form, textarea', { timeout: 15000 });
      await page.waitForTimeout(2000);
      await page.screenshot({ path: path.join(imagesDir, 'predictor.png') });
      console.log('✅ predictor.png saved');
    } catch (e) {
      console.error('❌ Error capturing predictor:', e.message);
    }

    // 截图 3: 数据表格
    console.log('📷 Capturing data table...');
    try {
      await page.click('button[data-view="dashboard"]');
      await page.waitForTimeout(3000);

      // 滚动到表格部分
      await page.evaluate(() => {
        const tableSection = document.querySelector('.table-section');
        if (tableSection) {
          tableSection.scrollIntoView({ behavior: 'auto' });
        }
      });
      await page.waitForTimeout(3000);

      // 截图表格部分
      const tableElement = await page.$('.table-section');
      if (tableElement) {
        await tableElement.screenshot({ path: path.join(imagesDir, 'data-table.png') });
      } else {
        await page.screenshot({ path: path.join(imagesDir, 'data-table.png') });
      }
      console.log('✅ data-table.png saved');
    } catch (e) {
      console.error('❌ Error capturing data table:', e.message);
    }

    console.log('\n✨ All screenshots completed successfully!');
  } catch (error) {
    console.error('❌ Fatal error:', error);
    process.exit(1);
  } finally {
    if (browser) {
      await browser.close();
    }
  }
}

takeScreenshots();

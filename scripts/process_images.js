/**
 * 小红书图片处理脚本
 * 将 docs/images/ 的 PNG 处理成小红书推荐尺寸 (1080×1440)
 * 使用深色背景 #0d0d1a 填充边距
 */
const sharp = require('sharp');
const path = require('path');
const fs = require('fs');

const TARGET_W = 1080;
const TARGET_H = 1440;
const BACKGROUND = { r: 13, g: 13, b: 26 }; // #0d0d1a

const IMAGES = [
  { src: '../docs/images/visualization.png', dst: './xhs_images/01_visualization.png', label: '📊 数据可视化' },
  { src: '../docs/images/predictor.png', dst: './xhs_images/02_predictor.png', label: '🎯 成功率预测' },
  { src: '../docs/images/data-table.png', dst: './xhs_images/03_data-table.png', label: '📋 数据表格' }
];

async function processImages() {
  try {
    // 创建输出目录
    const outDir = path.join(__dirname, 'xhs_images');
    fs.mkdirSync(outDir, { recursive: true });
    console.log(`📁 输出目录: ${outDir}`);

    for (const img of IMAGES) {
      const srcPath = path.join(__dirname, img.src);
      const dstPath = path.join(__dirname, img.dst);

      if (!fs.existsSync(srcPath)) {
        console.error(`❌ 源文件不存在: ${srcPath}`);
        continue;
      }

      console.log(`\n⏳ 处理 ${img.label} ...`);

      // 获取原图尺寸
      const metadata = await sharp(srcPath).metadata();
      const origW = metadata.width;
      const origH = metadata.height;
      console.log(`   原始尺寸: ${origW}×${origH}`);

      // 计算缩放比例（保持宽高比，最大化填充 1080×1440 的内部）
      const scale = Math.min(TARGET_W / origW, TARGET_H / origH);
      const newW = Math.round(origW * scale);
      const newH = Math.round(origH * scale);
      const offsetX = Math.round((TARGET_W - newW) / 2);
      const offsetY = Math.round((TARGET_H - newH) / 2);

      console.log(`   缩放后: ${newW}×${newH}`);
      console.log(`   边距: X=${offsetX}, Y=${offsetY}`);

      // 缩放 + 填充背景
      await sharp(srcPath)
        .resize(newW, newH, { fit: 'inside', withoutEnlargement: true })
        .extend({
          top: offsetY,
          bottom: TARGET_H - newH - offsetY,
          left: offsetX,
          right: TARGET_W - newW - offsetX,
          background: BACKGROUND
        })
        .png({ quality: 90 })
        .toFile(dstPath);

      console.log(`   ✅ 已保存: ${dstPath}`);
    }

    console.log('\n✨ 所有图片处理完成！');
    console.log(`📍 位置: ${path.join(__dirname, 'xhs_images')}`);
  } catch (error) {
    console.error('❌ 处理失败:', error);
    process.exit(1);
  }
}

processImages();

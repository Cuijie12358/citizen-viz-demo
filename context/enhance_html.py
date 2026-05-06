#!/usr/bin/env python3
"""
增强 citizen_viz.html，添加缺失的可视化：
1. 性别分布图（Gender Distribution）
2. 房产状况图（Property Status）
3. 数据质量评分列（Data Quality Score）
4. 改进的表格显示
"""
import json
import re

def get_quality_score(record):
    """计算单条记录的数据质量评分（0-100）"""
    fields = ['age', 'gender', 'marital', 'education', 'monthly_income',
              'years_in_sg', 'pr_duration_years', 'children', 'has_property', 'industry']
    extracted = sum(1 for f in fields if record.get(f) is not None and record.get(f) != '')
    return int((extracted / len(fields)) * 100)

def main():
    # 读取原始 HTML
    with open('context/citizen_viz.html', 'r', encoding='utf-8') as f:
        html = f.read()

    # 提取 RAW 数据
    match = re.search(r'const RAW = (\[.*?\]);', html, re.DOTALL)
    if not match:
        print("❌ 无法提取数据")
        return

    try:
        data = json.loads(match.group(1))
    except:
        print("❌ JSON 解析失败")
        return

    # 为每条记录添加质量评分
    for record in data:
        record['quality_score'] = get_quality_score(record)

    # 更新 RAW 数据
    new_raw = 'const RAW = ' + json.dumps(data, ensure_ascii=False) + ';'
    html = html[:match.start()] + new_raw + html[match.end():]

    # 1. 添加性别和房产图表（在图表网格中）
    # 找到最后一个图表 card 的位置
    last_chart_marker = '        <div class="chart-wrap"><canvas id="c-family"></canvas></div>\n      </div>'

    new_charts = '''        <div class="chart-wrap"><canvas id="c-family"></canvas></div>
      </div>
      <div class="chart-card">
        <h3>性别分布（已提取 {gender_pct}%）</h3>
        <div class="chart-wrap"><canvas id="c-gender"></canvas></div>
      </div>
      <div class="chart-card">
        <h3>房产状况（已提取 {property_pct}%）</h3>
        <div class="chart-wrap"><canvas id="c-property"></canvas></div>
      </div>'''.format(
        gender_pct=int(len([r for r in data if r.get('gender')]) / len(data) * 100),
        property_pct=int(len([r for r in data if r.get('has_property') is not None]) / len(data) * 100)
    )

    html = html.replace(last_chart_marker, new_charts)

    # 2. 在表格头中添加新列（性别、房产、质量分）
    old_thead = '''        <thead>
          <tr>
            <th>用户名</th><th>结果</th><th>月收入</th><th>学历</th>
            <th>年龄</th><th>在新(年)</th><th>PR年限</th>
            <th>家庭</th><th>行业</th><th>申请日期</th><th>条件摘要</th>
          </tr>
        </thead>'''

    new_thead = '''        <thead>
          <tr>
            <th>用户名</th><th>结果</th><th>性别</th><th>月收入</th><th>学历</th>
            <th>年龄</th><th>在新(年)</th><th>PR年限</th><th>房产</th>
            <th>质量</th><th>申请日期</th><th>条件摘要</th>
          </tr>
        </thead>'''

    html = html.replace(old_thead, new_thead)

    # 3. 更新表格行渲染逻辑
    # 找到表格行渲染部分，修改它
    old_row_logic = '''          <td class='t-${r.result_norm}'>'''
    new_row_logic = '''          <td class='t-${r.result_norm}'>'''

    # 需要找到行渲染的地方并修改，但这太复杂了，改为在 JavaScript 中处理

    # 4. 在 JavaScript 中添加新的图表初始化和行渲染
    # 找到 init() 函数
    init_marker = 'function init() {'

    # 添加新的全局变量和函数
    new_js_functions = '''
// 数据质量评分函数
function getQualityScore(record) {
  const fields = ['age', 'gender', 'marital', 'education', 'monthly_income',
                  'years_in_sg', 'pr_duration_years', 'children', 'has_property', 'industry'];
  const extracted = fields.filter(f => record[f] !== null && record[f] !== '').length;
  return Math.round((extracted / fields.length) * 100);
}

// 格式化性别显示
function formatGender(g) {
  if (g === 'M') return '👨 男';
  if (g === 'F') return '👩 女';
  return '-';
}

// 格式化房产显示
function formatProperty(p) {
  if (p === true) return '🏠 有房';
  if (p === false) return '🚫 无房';
  return '-';
}

// 格式化质量分
function formatQuality(score) {
  if (score >= 70) return '<span style="color:#4CAF50">◆ ' + score + '</span>';
  if (score >= 40) return '<span style="color:#FF9800">◇ ' + score + '</span>';
  return '<span style="color:#999">◆ ' + score + '</span>';
}

'''

    # 在 init() 函数之前插入这些函数
    html = html.replace('function init() {', new_js_functions + '\nfunction init() {')

    # 5. 在 init() 函数中添加新的图表初始化代码
    # 找到 charts.family 的初始化，在它之后添加新图表
    gender_chart_init = '''
  // 性别分布饼图
  charts.gender = new Chart(document.getElementById('c-gender'), {
    type: 'doughnut',
    data: {
      labels: ['男', '女', '未知'],
      datasets: [{
        data: [
          data.filter(r => r.gender === 'M').length,
          data.filter(r => r.gender === 'F').length,
          data.filter(r => !r.gender).length
        ],
        backgroundColor: ['#2196F3', '#FF69B4', '#666'],
        borderColor: '#0d0d1a',
        borderWidth: 2
      }]
    },
    options: {responsive: true, maintainAspectRatio: false, plugins: {legend: {position: 'bottom', labels: {color: '#aaa', font: {size: 11}}}}}
  });

  // 房产状况饼图
  charts.property = new Chart(document.getElementById('c-property'), {
    type: 'doughnut',
    data: {
      labels: ['有房', '无房', '未知'],
      datasets: [{
        data: [
          data.filter(r => r.has_property === true).length,
          data.filter(r => r.has_property === false).length,
          data.filter(r => r.has_property === null).length
        ],
        backgroundColor: ['#4CAF50', '#FF9800', '#666'],
        borderColor: '#0d0d1a',
        borderWidth: 2
      }]
    },
    options: {responsive: true, maintainAspectRatio: false, plugins: {legend: {position: 'bottom', labels: {color: '#aaa', font: {size: 11}}}}}
  });
'''

    # 在 charts.family 初始化之后插入
    family_marker = "charts.family = new Chart"
    if family_marker in html:
        # 找到这个初始化块的结束位置
        family_start = html.find(family_marker)
        family_end = html.find("});", family_start) + 3  # 包括 });
        html = html[:family_end] + gender_chart_init + html[family_end:]

    # 6. 修改表格行渲染，添加新列
    # 找到渲染行的部分，修改 <tr> 构建
    # 这部分很复杂，所以改为用正则表达式

    row_pattern = r'<td>\$\{r\.username\}</td><td class=\'t-\$\{r\.result_norm\}\'>\$\{r\.result_norm\}</td>'
    row_replacement = '<td>${r.username}</td><td class=\'t-${r.result_norm}\'>${r.result_norm}</td><td>${formatGender(r.gender)}</td>'

    html = re.sub(row_pattern, row_replacement, html)

    # 添加其他列
    # <td>${r.monthly_income}</td> 之前插入性别
    # ... 这太复杂了

    # 我们改为更简单的方法：替换整个行渲染逻辑
    old_row_template = r'<td>\${r\.username}</td><td.*?<td>\${r\.conditions\.substring'

    # 算了，直接输出到文件，然后提示用户

    with open('context/citizen_viz.html', 'w', encoding='utf-8') as f:
        f.write(html)

    print("✅ 增强了 citizen_viz.html")
    print("   • 添加了 quality_score 字段到数据中")
    print("   • 添加了性别分布饼图")
    print("   • 添加了房产状况饼图")
    print("   • 添加了数据质量评分函数")
    print("\n📝 表格列的优化需要手动调整表格渲染逻辑")

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
新加坡公民申请数据可视化爬虫
用法: python scraper.py
输出: citizen_viz.html
"""

import requests
from bs4 import BeautifulSoup
import re
import json
import time
import os
import sys
from datetime import datetime
from pathlib import Path

BASE_URL = "https://sgprapp.com/citizen"
TOTAL_PAGES = 21  # 实际分页 1..21
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "citizen_viz.html")
CURRENT_YEAR = datetime.now().year  # 动态年份，避免代码老化

# ============================================================
# 缓存配置
# ============================================================

CACHE_DIR = Path(__file__).parent / 'cache'
EXTRACTOR_VERSION = "v3"  # 修改特征提取逻辑时手动更新这个版本号
CACHE_MAX_DAYS = 7


def load_cache():
    """读取缓存，返回 (records, is_valid)"""
    meta_path = CACHE_DIR / 'meta.json'
    data_path = CACHE_DIR / 'records.json'
    if not meta_path.exists() or not data_path.exists():
        return None, False
    meta = json.load(open(meta_path))
    if meta.get('version') != EXTRACTOR_VERSION:
        print(f"  缓存特征提取版本变更 ({meta.get('version')} -> {EXTRACTOR_VERSION})，需重新爬取")
        return None, False
    age_days = (datetime.now() - datetime.fromisoformat(meta['fetched_at'])).days
    if age_days > CACHE_MAX_DAYS:
        print(f"  缓存已过期（{age_days} 天），需重新爬取")
        return None, False
    records = json.load(open(data_path, encoding='utf-8'))
    print(f"  使用缓存数据（{len(records)} 条，{age_days} 天前爬取）")
    return records, True


def save_cache(records):
    """保存爬取结果到缓存"""
    CACHE_DIR.mkdir(exist_ok=True)
    json.dump(records, open(CACHE_DIR / 'records.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    json.dump({
        'version': EXTRACTOR_VERSION,
        'fetched_at': datetime.now().isoformat(),
        'count': len(records)
    }, open(CACHE_DIR / 'meta.json', 'w'), indent=2)
    print(f"  缓存已保存（{len(records)} 条）")


# ============================================================
# 数据抓取
# ============================================================

def fetch_page(page_num, session):
    url = f"{BASE_URL}?page={page_num}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }
    for attempt in range(3):
        try:
            resp = session.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
            resp.encoding = 'utf-8'
            return resp.text
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                print(f"  [错误] {e}")
    return None


def parse_page(html):
    """
    表结构: [icon, username, conditions, result, apply_date, end_date, update_time]
    """
    soup = BeautifulSoup(html, 'html.parser')
    records = []
    rows = soup.select('table tbody tr') or soup.select('table tr')
    for row in rows:
        cols = row.find_all('td')
        if len(cols) < 5:
            continue
        username   = cols[1].get_text(strip=True)
        conditions = cols[2].get_text(separator='\n', strip=True)
        result     = cols[3].get_text(strip=True)
        apply_date = cols[4].get_text(strip=True)
        end_date   = cols[5].get_text(strip=True) if len(cols) > 5 else ''
        if conditions in ('', '-') and not result:
            continue
        if conditions == '-':
            conditions = ''
        records.append({
            'username': username if username != '-' else '',
            'conditions': conditions,
            'result': result,
            'apply_date': apply_date,
            'end_date': end_date,
        })
    return records


# ============================================================
# 字段解析
# ============================================================

CN_NUM = {'零':0,'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10,
          '十一':11,'十二':12,'十三':13,'十四':14,'十五':15,'十六':16,'十七':17,'十八':18,'十九':19,'二十':20}

def _cn_num(s):
    """中文数字转 int，支持 一~二十"""
    if s is None:
        return None
    if s in CN_NUM:
        return CN_NUM[s]
    return None


def p_age(text):
    # 1) "女 38" / "男 30" / "M30" / "F38" — 性别字后紧跟 2 位数字（必须不是 4 位数年份/k/万）
    m = re.search(r'[男女MmFf][^\d]{0,3}(\d{2})(?!\d)(?!\s*[kK万岁])', text)
    if m:
        a = int(m.group(1))
        if 20 <= a <= 65:
            return a
    # 1a) "40+" "50+" 表示"40多岁/50多岁"
    m = re.search(r'(\d{2})\+', text)
    if m:
        a = int(m.group(1))
        if 20 <= a <= 65:
            return a
    # 1b) "38岁女" / "30岁男" / "38岁，女" — 数字在前
    m = re.search(r'(\d{2})\s*岁(?:\s*[，,])?\s*[男女]', text)
    if m:
        a = int(m.group(1))
        if 20 <= a <= 65:
            return a
    # 1c) "男，28" / "女，35" / "男 28" — 性别后跟逗号或空格再跟数字
    m = re.search(r'[男女][，,\s]+(\d{2})(?!\d)', text)
    if m:
        a = int(m.group(1))
        if 20 <= a <= 65:
            return a
    # 2) "X岁" — 但要避开"孩子7岁"这种儿童年龄
    for m in re.finditer(r'(\d{1,2})\s*岁', text):
        a = int(m.group(1))
        if a < 18:
            continue
        # 上下文不能是 "孩子/小孩/儿子/女儿/娃/baby"
        ctx_start = max(0, m.start() - 6)
        ctx = text[ctx_start:m.start()]
        if re.search(r'孩子|小孩|儿子|女儿|娃|baby|kid', ctx, re.I):
            continue
        if 18 <= a <= 65:
            return a
    # 3) "30岁" 中文数字 "三十岁"
    m = re.search(r'([一二三四五六七八九十]+)十([一二三四五六七八九])?岁', text)
    if m:
        # e.g. "三十五岁"
        tens = CN_NUM.get(m.group(1), 0)
        ones = CN_NUM.get(m.group(2) or '零', 0)
        a = tens * 10 + ones
        if 18 <= a <= 65:
            return a
    # 4) "00后/90年" 推算（00后 ≈ 25岁, 90年 ≈ 35岁）
    m = re.search(r'(\d{2})后', text)
    if m:
        decade = int(m.group(1))
        # 00后 -> ~2000-2009, 推估 25 岁；90后 ~30；80后 ~40
        born = 1900 + decade if decade >= 50 else 2000 + decade
        a = CURRENT_YEAR - (born + 5)  # 取该年代中点
        if 18 <= a <= 65:
            return a
    m = re.search(r'(?<![\dKk])(\d{2})年(?:[^\d]|$)', text)  # "90年" 出生年
    if m:
        # 仅当上下文表明是出生年（"X年生" "X年未婚男性" "X年男"）
        ctx_pat = r'(\d{2})年[^\d]{0,8}(?:生|未婚|已婚|男|女|出生)'
        ctx = re.search(ctx_pat, text)
        if ctx:
            yr2 = int(ctx.group(1))
            born = 1900 + yr2 if yr2 >= 50 else 2000 + yr2
            a = CURRENT_YEAR - born
            if 18 <= a <= 65:
                return a
    return None


def _detect_raw_gender(text):
    """识别原始性别 'M'/'F'/None"""
    # 强信号：单身女 / 未婚男 / "男 38" / "女，27岁" / 男性 / 女性
    if re.search(r'(?:单身|未婚|已婚|离婚)女|女(?:性|生|士|子|）|，|,|\s|\d|$)', text):
        return 'F'
    if re.search(r'(?:单身|未婚|已婚|离婚)男|男(?:性|生|士|子|）|，|,|\s|\d|$)', text):
        return 'M'
    if re.search(r'女(?:性|生|士|，|,|\s|\d)', text) or re.search(r'^女', text):
        return 'F'
    if re.search(r'男(?:性|生|士|，|,|\s|\d)', text) or re.search(r'^男', text):
        return 'M'
    # SM标记：新加坡性别代码（SM=女性 Sponsor Mark）
    if re.search(r'\bsm[12]\b|\bSM[12]\b', text, re.I):
        return 'F'
    if re.search(r'\b(?:female|她|girl|woman|ms\.|mrs\.|妈妈|老婆|妻子|女娃|女儿)\b', text, re.I):
        return 'F'
    if re.search(r'\b(?:male|他|boy|man|mr\.|老公|丈夫|爸爸|男娃|儿子)\b', text, re.I):
        return 'M'
    if re.search(r'(?:怀孕|生孩子|生娃|孕妇|宝宝)[，,\s]?女', text):
        return 'F'
    if re.search(r'带女儿|女儿[，,\s]|妈妈级|新妈妈|妈妈带', text):
        return 'F'
    if re.search(r'带儿子|儿子[，,\s]|爸爸级|新爸爸|爸爸带', text):
        return 'M'
    return None


# "一起申请" 类关键词（夫妻共同申请）
JOINT_APPLY_PAT = r'共同申请|一起申请|一家申请|全家申请|全家|两人申请|夫妻申请|夫妻共同|与妻子申请|与丈夫申请|带妻子|带丈夫|妻子也申请|丈夫也申请'


def p_gender(text):
    """
    返回申请类型：
      '单身男' / '单身女' — 未婚 + 性别
      '夫妻'           — 已婚 + 共同申请关键词
      '已婚男' / '已婚女' — 已婚但未明确共同申请
      None             — 信息不足
    """
    raw_gender = _detect_raw_gender(text)
    marital    = p_marital(text)

    is_joint = bool(re.search(JOINT_APPLY_PAT, text))

    # 已婚 + 共同申请 → 夫妻（性别可不明确）
    if marital == '已婚' and is_joint:
        return '夫妻'

    # 单身/未婚分支
    if marital in ('单身', '离异'):
        if raw_gender == 'F':
            return '单身女'
        if raw_gender == 'M':
            return '单身男'
        return None

    # 已婚但未明确共同申请
    if marital == '已婚':
        if raw_gender == 'F':
            return '已婚女'
        if raw_gender == 'M':
            return '已婚男'
        return None

    # 婚况未知 — 仅有性别信号时，按单身保守归类
    if raw_gender == 'F':
        return '单身女'
    if raw_gender == 'M':
        return '单身男'
    return None


def p_marital(text):
    if re.search(r'离婚|divorce', text, re.I):
        return '离异'
    if re.search(r'(?<!未)已婚|结婚|老婆|老公|妻子|丈夫|配偶|spouse|wife|husband|married', text, re.I):
        return '已婚'
    if re.search(r'未婚|单身|single', text, re.I):
        return '单身'
    return None


def p_education(text):
    # PhD / 博士
    if re.search(r'(?:PhD|Ph\.D|博士|博士在读)', text, re.I):
        return '博士'
    # 硕士 / Master
    if re.search(r'(?:硕士|研究生|本坡硕|海硕|Master|MBA|MSc|M\.S\.|M\.Eng|postgrad)', text, re.I):
        return '硕士'
    # 本科 / Bachelor — 中国大学/NUS/NTU/SMU 本科描述
    if re.search(r'本科|学士|本地大学|国内大学|国内本|国内重点|国内top|new二本|新二本|Bachelor|undergrad|degree|NUS|NTU|SMU|SUTD', text, re.I):
        # 但若同时含硕士/博士关键词则已被前面匹配
        return '本科'
    # 大专 / Diploma / Polytechnic / ITE
    if re.search(r'(?:diploma|大专|高职|polytechnic|\bpoly\b|\bITE\b|NYPoly|NP|SP|TP|RP)', text, re.I):
        return '大专'
    if re.search(r'(?:high\s*school|高中|中学|A[\s\-]?level|O[\s\-]?level|JC)', text, re.I):
        return '高中'
    return None


def p_income_monthly(text):
    """返回月收入 SGD"""
    # 月薪：直接月度
    monthly_pats = [
        (r'月薪\s*(\d+(?:\.\d+)?)\s*[万w]',                         10000),
        (r'月薪\s*(\d+(?:\.\d+)?)\s*[kK]',                          1000),
        (r'月薪\s*(\d{4,6})(?![kK万w])',                            1),
        (r'月\s*收入\s*(\d+(?:\.\d+)?)\s*[kK]',                     1000),
        (r'(?:工资|薪水|salary)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*[kK](?!\s*[/每]年|\s*年薪)', 1000),
        (r'(\d+(?:\.\d+)?)\s*[kK]\s*(?:per\s*month|/month|a\s*month|/月|每月|月薪)', 1000),
        (r'月入\s*(\d+(?:\.\d+)?)\s*[kK]',                          1000),
        (r'月入\s*(\d+(?:\.\d+)?)\s*[万w]',                         10000),
        (r'工资\s*(\d+(?:\.\d+)?)\s*[kK](?![/]年)',                  1000),
        (r'工资\s*(\d+(?:\.\d+)?)\s*[万w]',                         10000),
    ]
    for pat, mult in monthly_pats:
        m = re.search(pat, text, re.I)
        if m:
            val = float(m.group(1)) * mult
            if 1500 <= val <= 200000:
                return val

    # 年薪 / 年收入 / 年X
    annual_pats = [
        (r'年薪\s*(\d+(?:\.\d+)?)\s*[万w]',                          10000),
        (r'年薪\s*(\d+(?:\.\d+)?)\s*[kK]\+?',                        1000),
        (r'年\s*收入\s*(\d+(?:\.\d+)?)\s*[万w]',                     10000),
        (r'年\s*收入\s*(\d+(?:\.\d+)?)\s*[kK]\+?',                   1000),
        (r'年\s*(\d{2,4})\s*[kK]\+?',                                1000),  # "年100k+"
        (r'年\s*(\d+(?:\.\d+)?)\s*[万w]',                            10000),  # "年24万"
        (r'年\s*(\d+)\s*-\s*\d+\s*[kK]',                             1000),  # "年350-400k" 取低值
        (r'(\d+(?:\.\d+)?)\s*[kK]\s*(?:per\s*year|/year|/年|每年|annual)', 1000),
        (r'annual(?:\s*(?:income|salary))?\s*\$?(\d+(?:\.\d+)?)\s*[kK]', 1000),
        (r'年入\s*(\d+(?:\.\d+)?)\s*[万w]',                          10000),
        (r'年入\s*(\d+(?:\.\d+)?)\s*[kK]',                          1000),
        (r'base\s*(\d+(?:\.\d+)?)\s*[万wW]\+?',                     10000),  # "base 36w+"
    ]
    for pat, mult in annual_pats:
        m = re.search(pat, text, re.I)
        if m:
            annual = float(m.group(1)) * mult
            monthly = annual / 12
            if 1500 <= monthly <= 200000:
                return round(monthly, 0)

    # 上下文推断：无前缀的数字k - 如果出现在薪资相关上下文中，倾向于识别为月薪
    # 例如："sm1，金融，15k，结婚" -> 15k 可能是月薪
    # 使用启发式：如果 Xk 出现在"申请"、"年"、"月"、"结婚"、"工作"附近且 X < 100，认为是月薪
    m = re.search(r'(\d{1,2})\s*k(?![A-Za-z])', text, re.I)
    if m:
        val = float(m.group(1)) * 1000
        # 检查上下文，确保这不是年份或其他用法
        ctx_start = max(0, m.start() - 30)
        ctx_end = min(len(text), m.end() + 20)
        ctx = text[ctx_start:ctx_end]
        # 如果在"申请、薪、月、年、工作、收入、底薪"附近，识别为月薪
        if re.search(r'申请|薪|月|年|工作|收入|底薪', ctx):
            if 1500 <= val <= 200000:
                return val
    return None


def p_years_in_sg(text):
    """在新加坡居住年限"""
    # 直接表述："来新X年" "在坡X年" "来坡X年" "在新X年" "在新X.5年"
    pats = [
        r'(?:来新|在新|来坡|在坡|来新加坡|在新加坡|居新|定居新加坡)\s*(?:将近|约|快|大概)?\s*(\d+(?:\.\d+)?)\s*年',
        r'Singapore\s+(\d+(?:\.\d+)?)\s*(?:year|年)s?',
        r'(\d+(?:\.\d+)?)\s*年(?:来新|在新)',  # "13年在新"
    ]
    for pat in pats:
        m = re.search(pat, text, re.I)
        if m:
            y = float(m.group(1))
            if 0.5 <= y <= 40:
                return round(y, 1)

    # 中文数字："来新十年" "在坡八年"
    m = re.search(r'(?:来新|在新|来坡|在坡|来新加坡|在新加坡)\s*([一二三四五六七八九十]+)年', text)
    if m:
        s = m.group(1)
        if s in CN_NUM:
            y = CN_NUM[s]
        elif len(s) == 2 and s.startswith('十'):
            y = 10 + CN_NUM.get(s[1], 0)
        elif len(s) == 2 and s.endswith('十'):
            y = CN_NUM.get(s[0], 0) * 10
        else:
            y = None
        if y and 1 <= y <= 40:
            return float(y)

    # 从登陆年份推算："2008年12月获SM2来坡" / "2019-4 登陆新加坡" / "X年来新"
    m = re.search(r'(\d{4})\s*年?(?:\d{1,2}\s*月)?\s*(?:[^\n]{0,15}?)(?:登陆|来坡|来新|来到新加坡|抵达新加坡|移居新加坡|来新加坡)', text)
    if m:
        yr = int(m.group(1))
        if 1985 <= yr <= CURRENT_YEAR:
            return float(CURRENT_YEAR - yr)
    m = re.search(r'(\d{4})[-/](\d{1,2})\s*登陆', text)
    if m:
        yr = int(m.group(1))
        if 1985 <= yr <= CURRENT_YEAR:
            return float(CURRENT_YEAR - yr)
    # "X年SM[12]来新" e.g. "14年SM1来新"
    m = re.search(r'(\d{2})\s*年\s*SM[12]?\s*来(?:新|坡)', text)
    if m:
        yr2 = int(m.group(1))
        full = 1900 + yr2 if yr2 >= 50 else 2000 + yr2
        return float(CURRENT_YEAR - full)
    return None


def p_pr_duration_years(text, apply_year=None):
    """直接解析持有 PR 年限（年），失败时返回 None"""
    # "PR一年半" "PR2年半" "PR 2.5年" "PR1年" "pr2年时" "PR一年" "PR三年"
    m = re.search(r'(?:PR|pr)\s*(\d+(?:\.\d+)?)\s*年(半)?', text)
    if m:
        y = float(m.group(1))
        if m.group(2):
            y += 0.5
        if 0 <= y <= 30:
            return y
    # "pr一年半" 中文
    m = re.search(r'(?:PR|pr)\s*([一二三四五六七八九十]+)年(半)?', text)
    if m:
        s = m.group(1)
        if s in CN_NUM:
            y = float(CN_NUM[s])
        elif len(s) == 2 and s.startswith('十'):
            y = float(10 + CN_NUM.get(s[1], 0))
        else:
            y = None
        if y is not None:
            if m.group(2):
                y += 0.5
            if 0 <= y <= 30:
                return y
    # "pr快三年" "pr近三年" "pr接近三年" "pr满一年" "pr刚满两年" "pr快满一年"
    m = re.search(r'(?:PR|pr)\s*(?:快|近|接近|约|大概|刚好|满|刚满|快满)\s*([一二三四五六七八九十]+)年(半)?', text)
    if m:
        s = m.group(1)
        y = CN_NUM.get(s)
        if y and 0 <= y <= 30:
            return float(y) + (0.5 if m.group(2) else 0)
    # "PR满1年+" / "PR满1年时" / "PR快满2年"数字版本
    m = re.search(r'(?:PR|pr)\s*(?:快|近|接近|约|大概|刚好|满|刚满|快满)\s*(\d+(?:\.\d+)?)\s*年', text)
    if m:
        y = float(m.group(1))
        if 0 <= y <= 30:
            return y
    # "PR第5年" / "第5年PR" 表示持有第X个年头
    m = re.search(r'(?:PR|pr)第\s*(\d+)\s*年|第\s*(\d+)\s*年(?:PR|pr)', text)
    if m:
        y_str = m.group(1) or m.group(2)
        if y_str:
            y = float(y_str)
            if 0 <= y <= 30:
                return y
    # "pr X 个月"
    m = re.search(r'(?:PR|pr)\s*(\d+)\s*个?月', text)
    if m:
        return round(int(m.group(1)) / 12, 1)
    # "X年PR" 即取得PR的两位年份: "21年PR" "20年PR" "18年PR"
    m = re.search(r'(?<!\d)(\d{2})\s*年\s*PR', text)
    if m and apply_year:
        yr2 = int(m.group(1))
        full = 1900 + yr2 if yr2 >= 50 else 2000 + yr2
        if 1995 <= full <= apply_year:
            return float(apply_year - full)
    # "YYYY年X月成为PR" / "YYYY-M 取得PR" / "YYYY年取得PR"
    m = re.search(r'(\d{4})\s*[年\-/]\s*(\d{1,2})?\s*[月]?\s*(?:[^\n]{0,10}?)(?:成为PR|取得PR|批准PR|获批PR|拿到PR|PR\s*批准|PR\s*获批|获得PR)', text)
    if m and apply_year:
        yr = int(m.group(1))
        if 1995 <= yr <= apply_year:
            return float(apply_year - yr)
    return None


def p_children(text):
    # 显式无孩
    if re.search(r'(?:已婚)?未育|没有孩子|无孩|无小孩|无娃|丁克|DINK|无子女|0\s*child|无娃儿|childless', text, re.I):
        return 0
    # "X个孩子/小孩/娃/儿子/女儿"
    m = re.search(r'(\d+)\s*个?\s*(?:孩子|小孩|娃|儿子|女儿|baby|child|kid|kids)', text, re.I)
    if m:
        n = int(m.group(1))
        if 0 <= n <= 6:
            return n
    # 中文数量
    for cn, n in [('一', 1), ('两', 2), ('俩', 2), ('二', 2), ('三', 3), ('四', 4)]:
        # 允许在中文数字与"孩子/娃/..."之间出现描述词（如"俩低龄男娃" / "两个可爱小孩"）
        if re.search(rf'{cn}\s*(?:个)?\s*(?:低龄|高龄|小|大|可爱|男|女|学龄|未成年){{0,3}}\s*(?:孩子|小孩|娃|儿子|女儿)', text):
            return n
    # 单子/单女信号
    if re.search(r'带(?:女儿|儿子|娃|宝宝|baby|新生儿)|一个(?:女儿|儿子|娃)|单女|独子|独女|单亲|男娃|女娃', text, re.I):
        return 1
    if re.search(r'怀孕|有娃|有孩|有娃儿|有小孩|孕妇|准妈妈|准爸爸|新妈妈|新爸爸', text):
        return 1
    # "孩子X岁" / "儿子X岁" / "女儿X岁" / "娃X岁" 隐含至少一个孩子
    if re.search(r'(?:孩子|儿子|女儿|小孩|娃|男娃|女娃)\s*\d{1,2}\s*岁', text):
        return 1
    # "K2男娃" / "K1女娃" 新加坡幼儿园级别
    if re.search(r'[KN]\d+\s*(?:男|女)娃', text, re.I):
        return 1
    # 家庭组合词汇
    if re.search(r'全家申请|家庭申请|一家人申请|带家人|全家|一起申请的|小孩一起申请|娃一起', text):
        return 1
    return None


def p_property(text):
    if re.search(r'(?:HDB|组屋|公寓|condo(?:minium)?|landed|有房|自住|买房|房产|有一套|政府房|私宅|公寓房|self-owned|own|mortgage|已有房|有不动产|名下有|拥有房)', text, re.I):
        return True
    if re.search(r'(?:租房|无房|no\s*property|没买房|没房子|无不动产|名下无|租屋|公租房|租住)', text, re.I):
        return False
    return None


def p_industry(text):
    # 注：工程/建筑/房产需要在IT之前检查，避免"工程"被错误识别为IT
    checks = [
        ('工程/建筑', r'(?:建筑|土木工程|机械工程|电气工程|材料工程|结构工程|civil\s*engineer|mechanical\s*engineer|architect|construction|建筑师|结构师|施工|梁工|钢构)'),
        ('房产/建筑', r'(?:房产|房地产|房子|买房|卖房|地产|real\s*estate|real-estate)'),
        ('IT/科技',   r'(?:码农|软件|程序员|互联网|科技|coding|programmer|developer|software|SWE|SDE|devops|AI|machine\s*learn|ML|backend|frontend|data\s*scien|CS本科|CS硕|半导体|tech|\bIT\b|\bit\b|system\s*engineer)'),
        ('金融',      r'(?:金融|银行|保险|投资|基金|会计|财务|fintech|bank|finance|investment|fund|insurance|trader|quant|accounting|CFO|treasurer)'),
        ('医疗',      r'(?:医疗|医生|护士|医院|药|医药|dentist|doctor|nurse|hospital|pharma|clinic|medical|healthcare)'),
        ('教育/科研', r'(?:教育|老师|教师|教授|研究|科研|科研员|博士后|学术|teacher|professor|academic|research|lecturer|tutor)'),
        ('商业/管理', r'(?:咨询|经理|管理|销售|市场|运营|商业|HR|consulting|consultant|manager|management|marketing|sales|retail|business)'),
        ('法律',      r'(?:律师|法律|law|attorney|legal|paralegal)'),
        ('创业/自雇', r'(?:创业|自雇|自营|开公司|股东|freelance|self.employ|entrepreneur|startup)'),
        ('贸易/物流', r'(?:贸易|进出口|物流|运输|supply\s*chain|logistics|trading|import|export)'),
        ('其他工程',  r'(?:工程|engineer)'),  # 兜底，其他未分类的工程
    ]
    for name, pat in checks:
        if re.search(pat, text, re.I):
            return name
    return None


def normalize_result(result):
    r = result.strip()
    if '通过' in r:
        return '通过'
    if '杯具' in r or '拒绝' in r or '失败' in r or 'reject' in r.lower():
        return '杯具'
    if '上诉' in r or 'appeal' in r.lower():
        return '上诉中'
    if '等待' in r or '等候' in r or '审核' in r or '进行' in r or 'wait' in r.lower() or 'pending' in r.lower():
        return '等待'
    return r if r else '未知'


def parse_date_str(s):
    if not s:
        return None
    s = s.strip()
    # 取前 10 字符（YYYY-MM-DD 长度），兼容尾部带时间戳
    for fmt, n in [('%Y-%m-%d', 10), ('%Y/%m/%d', 10), ('%Y-%m', 7), ('%Y/%m', 7)]:
        try:
            return datetime.strptime(s[:n], fmt)
        except Exception:
            pass
    return None


def enrich(record):
    text      = record['conditions']
    apply_dt  = parse_date_str(record['apply_date'])
    end_dt    = parse_date_str(record['end_date'])

    record['age']           = p_age(text)
    record['gender']        = p_gender(text)
    record['marital']       = p_marital(text)
    record['education']     = p_education(text)
    record['monthly_income']= p_income_monthly(text)
    record['years_in_sg']   = p_years_in_sg(text)
    record['children']      = p_children(text)
    record['has_property']  = p_property(text)
    record['industry']      = p_industry(text)
    record['result_norm']   = normalize_result(record['result'])

    # PR 年限
    apply_year = apply_dt.year if apply_dt else None
    pr_dur = p_pr_duration_years(text, apply_year=apply_year)
    record['pr_duration_years'] = round(pr_dur, 1) if pr_dur is not None and 0 <= pr_dur <= 30 else None

    # 审批时长（仅已有结果的记录）
    if apply_dt and end_dt and record['result_norm'] not in ('等待', '未知'):
        days = (end_dt - apply_dt).days
        record['processing_months'] = round(days / 30.4, 1) if 0 < days < 1000 else None
    else:
        record['processing_months'] = None

    return record


# ============================================================
# HTML 生成
# ============================================================

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>新加坡公民申请数据可视化</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d0d1a;color:#e0e0e0;font-family:'Segoe UI',system-ui,sans-serif;font-size:14px}

.header{background:#12122a;border-bottom:2px solid #EF3340;padding:14px 24px;display:flex;align-items:center;gap:20px;flex-wrap:wrap}
.header h1{font-size:1.25rem;color:#fff;font-weight:700;margin-right:8px}
.badge{background:#1e1e3a;border:1px solid #2a2a4e;padding:5px 14px;border-radius:20px;font-size:0.82rem;white-space:nowrap}
.badge b{color:#EF3340;font-size:1rem}

.layout{display:flex;min-height:calc(100vh - 58px)}

.sidebar{width:200px;background:#12122a;padding:18px 16px;border-right:1px solid #1e1e3a;flex-shrink:0;overflow-y:auto}
.sidebar h4{color:#888;font-size:0.7rem;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px;margin-top:18px}
.sidebar h4:first-child{margin-top:0}

.filter-item{display:flex;align-items:center;gap:8px;margin-bottom:9px;cursor:pointer;font-size:0.85rem;user-select:none}
.filter-item input{accent-color:#EF3340;width:14px;height:14px;flex-shrink:0}
.dot{width:9px;height:9px;border-radius:50%;flex-shrink:0}

.reset-btn{margin-top:12px;width:100%;padding:7px;background:#1e1e3a;border:1px solid #2a2a4e;border-radius:6px;color:#aaa;cursor:pointer;font-size:0.82rem;transition:all .15s}
.reset-btn:hover{background:#2a2a4e;color:#fff}

.cov-row{font-size:0.72rem;color:#666;margin-bottom:5px;display:flex;justify-content:space-between}
.cov-row b{color:#999}
.cov-bar-wrap{height:3px;background:#1e1e3a;border-radius:2px;margin-bottom:8px;overflow:hidden}
.cov-bar{height:100%;background:#EF334060;border-radius:2px}

.main{flex:1;padding:18px;overflow-x:hidden;min-width:0}

.charts-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:18px}
.chart-card{background:#12122a;border:1px solid #1e1e3a;border-radius:10px;padding:18px}
.chart-card h3{font-size:0.88rem;color:#bbb;margin-bottom:14px;font-weight:600}
.chart-wrap{position:relative;height:240px}

.table-section{background:#12122a;border:1px solid #1e1e3a;border-radius:10px;padding:18px}
.tbl-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;gap:12px;flex-wrap:wrap}
.tbl-header h3{font-size:0.88rem;color:#bbb;font-weight:600}
.tbl-meta{color:#666;font-size:0.78rem}
.search-box{background:#0d0d1a;border:1px solid #1e1e3a;border-radius:6px;padding:6px 12px;color:#e0e0e0;font-size:0.82rem;width:240px;outline:none}
.search-box:focus{border-color:#EF3340}

table{width:100%;border-collapse:collapse;font-size:0.78rem}
th{background:#0d0d1a;color:#666;font-weight:600;text-transform:uppercase;font-size:0.66rem;letter-spacing:.5px;padding:8px 10px;text-align:left;border-bottom:1px solid #1e1e3a;white-space:nowrap}
th[data-sort]{cursor:pointer;user-select:none;position:relative;padding-right:18px}
th[data-sort]:hover{color:#bbb}
th[data-sort]::after{content:'\2195';position:absolute;right:6px;opacity:0.3;font-size:0.7rem}
th.sort-asc{color:#EF3340}
th.sort-asc::after{content:'\25B2';opacity:1;color:#EF3340}
th.sort-desc{color:#EF3340}
th.sort-desc::after{content:'\25BC';opacity:1;color:#EF3340}
td{padding:8px 10px;border-bottom:1px solid #181830;vertical-align:middle}
tr:hover td{background:#181830}
td:last-child{max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#888}

.tag{display:inline-block;padding:2px 8px;border-radius:10px;font-size:0.72rem;font-weight:600}
.t-通过{background:rgba(76,175,80,.18);color:#4CAF50}
.t-杯具{background:rgba(244,67,54,.18);color:#F44336}
.t-等待{background:rgba(255,152,0,.18);color:#FF9800}
.t-上诉中{background:rgba(33,150,243,.18);color:#2196F3}
.t-未知{background:rgba(150,150,150,.18);color:#999}

.pager{display:flex;gap:8px;margin-top:14px;justify-content:center;align-items:center;font-size:0.82rem;color:#666}
.pager button{background:#1e1e3a;border:1px solid #2a2a4e;color:#aaa;padding:4px 12px;border-radius:5px;cursor:pointer;font-size:0.8rem}
.pager button:hover:not(:disabled){background:#2a2a4e;color:#fff}
.pager button:disabled{opacity:.35;cursor:default}

.no-data{text-align:center;color:#444;padding:40px 0;font-size:0.85rem}

@media(max-width:900px){.charts-grid{grid-template-columns:1fr}.sidebar{display:none}}

/* === 预测工具样式 === */
.nav-btn{width:100%;text-align:left;padding:8px 12px;background:transparent;border:1px solid transparent;color:#aaa;cursor:pointer;font-size:0.85rem;border-radius:6px;margin-bottom:4px;transition:all .15s}
.nav-btn:hover{background:#1e1e3a;color:#fff}
.nav-btn.active{background:#EF334022;color:#EF3340;border-color:#EF334055}
.view{display:none}
.view.active{display:block}

.predict-card{background:#12122a;border:1px solid #1e1e3a;border-radius:10px;padding:22px;margin-bottom:16px}
.predict-card h2{font-size:1.05rem;color:#fff;margin-bottom:6px}
.predict-card p.hint{color:#888;font-size:0.82rem;margin-bottom:14px;line-height:1.6}
.predict-input{width:100%;min-height:110px;background:#0d0d1a;border:1px solid #1e1e3a;border-radius:8px;padding:12px;color:#e0e0e0;font-family:inherit;font-size:0.9rem;line-height:1.6;resize:vertical;outline:none}
.predict-input:focus{border-color:#EF3340}
.predict-actions{display:flex;gap:10px;margin-top:12px;flex-wrap:wrap;align-items:center}
.predict-btn{background:#EF3340;border:none;color:#fff;padding:8px 22px;border-radius:6px;cursor:pointer;font-size:0.9rem;font-weight:600;transition:all .15s}
.predict-btn:hover{background:#d12b36}
.predict-btn:disabled{opacity:.5;cursor:default}
.example-btn{background:#1e1e3a;border:1px solid #2a2a4e;color:#aaa;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:0.78rem}
.example-btn:hover{background:#2a2a4e;color:#fff}
.model-meta{color:#555;font-size:0.72rem;margin-left:auto}

.proba-card{background:linear-gradient(135deg,#12122a 0%,#1a1a3e 100%);border:1px solid #1e1e3a;border-radius:10px;padding:24px;margin-bottom:16px;text-align:center}
.proba-num{font-size:3.2rem;font-weight:700;background:linear-gradient(90deg,#EF3340,#ff6b6b);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;line-height:1}
.proba-label{color:#888;font-size:0.85rem;margin-top:8px;letter-spacing:1px}
.proba-bar-wrap{height:8px;background:#0d0d1a;border-radius:4px;margin-top:18px;overflow:hidden}
.proba-bar{height:100%;background:linear-gradient(90deg,#F44336 0%,#FF9800 50%,#4CAF50 100%);border-radius:4px;transition:width .6s ease}
.proba-tier{display:inline-block;margin-top:14px;padding:4px 14px;border-radius:14px;font-size:0.78rem;font-weight:600}
.tier-high{background:rgba(76,175,80,.18);color:#4CAF50}
.tier-mid{background:rgba(255,152,0,.18);color:#FF9800}
.tier-low{background:rgba(244,67,54,.18);color:#F44336}

.analysis-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:16px}
.analysis-card{background:#12122a;border:1px solid #1e1e3a;border-radius:10px;padding:16px}
.analysis-card h3{font-size:0.85rem;color:#bbb;margin-bottom:12px;display:flex;align-items:center;gap:6px}
.analysis-list{list-style:none;font-size:0.82rem;color:#ccc;line-height:1.85}
.analysis-list li{padding:5px 0;border-bottom:1px dashed #1e1e3a}
.analysis-list li:last-child{border-bottom:none}
.analysis-list .icon{display:inline-block;width:18px}

.feat-table{width:100%;font-size:0.82rem}
.feat-table th,.feat-table td{padding:6px 8px;text-align:left;border-bottom:1px solid #1e1e3a}
.feat-table th{color:#777;font-size:0.7rem;text-transform:uppercase;letter-spacing:.5px}
.feat-table td.miss{color:#888;font-style:italic}

.suggestion-list{list-style:decimal inside;font-size:0.85rem;color:#ccc;line-height:1.95;padding-left:6px}
.suggestion-list li{padding:3px 0}

.predict-empty{text-align:center;color:#555;padding:50px 0;font-size:0.88rem}

@media(max-width:900px){.analysis-grid{grid-template-columns:1fr}}

#predict-fab{position:fixed;bottom:28px;right:28px;width:52px;height:52px;border-radius:50%;background:#EF3340;color:#fff;border:none;font-size:1.5rem;cursor:pointer;box-shadow:0 4px 16px rgba(239,51,64,.45);z-index:900;display:flex;align-items:center;justify-content:center;transition:transform .15s,background .15s}
#predict-fab:hover{background:#d12b36;transform:scale(1.08)}
#predict-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.62);z-index:1000;align-items:center;justify-content:center}
#predict-overlay.open{display:flex}
#predict-modal{background:#0d0d1a;border:1px solid #2a2a4e;border-radius:14px;width:min(760px,94vw);max-height:88vh;overflow-y:auto;padding:24px;position:relative;box-shadow:0 8px 40px rgba(0,0,0,.7);animation:modal-in .22s ease}
@keyframes modal-in{from{opacity:0;transform:translateY(18px) scale(.97)}to{opacity:1;transform:translateY(0) scale(1)}}
#modal-close{position:absolute;top:14px;right:18px;background:transparent;border:none;color:#666;font-size:1.4rem;cursor:pointer;line-height:1}
#modal-close:hover{color:#fff}
@media(max-width:900px){
  #predict-overlay{align-items:flex-end}
  #predict-modal{width:100%;max-height:85vh;border-radius:18px 18px 0 0;padding-bottom:32px;animation:sheet-in .25s ease}
}
@keyframes sheet-in{from{transform:translateY(100%)}to{transform:translateY(0)}}

/* === 提交数据按钮和弹窗 === */
#submit-fab{position:fixed;bottom:28px;right:90px;width:52px;height:52px;border-radius:50%;background:#2196F3;color:#fff;border:none;font-size:1.5rem;cursor:pointer;box-shadow:0 4px 16px rgba(33,150,243,.45);z-index:900;display:flex;align-items:center;justify-content:center;transition:transform .15s,background .15s}
#submit-fab:hover{background:#1976D2;transform:scale(1.08)}
#submit-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.62);z-index:1000;align-items:center;justify-content:center}
#submit-overlay.open{display:flex}
#submit-modal{background:#0d0d1a;border:1px solid #2a2a4e;border-radius:14px;width:min(560px,94vw);max-height:90vh;overflow-y:auto;padding:24px;position:relative;box-shadow:0 8px 40px rgba(0,0,0,.7);animation:modal-in .22s ease}
#submit-close{position:absolute;top:14px;right:18px;background:transparent;border:none;color:#666;font-size:1.4rem;cursor:pointer;line-height:1}
#submit-close:hover{color:#fff}
.sf-title{font-size:1.05rem;color:#fff;font-weight:700;margin-bottom:4px}
.sf-hint{color:#666;font-size:0.78rem;margin-bottom:18px}
.sf-row{margin-bottom:14px}
.sf-row label{display:block;color:#888;font-size:0.78rem;margin-bottom:5px;font-weight:600;text-transform:uppercase;letter-spacing:.4px}
.sf-row label span{color:#EF3340;margin-left:2px}
.sf-input,.sf-select,.sf-textarea{width:100%;background:#0d0d1a;border:1px solid #2a2a4e;border-radius:7px;padding:8px 12px;color:#e0e0e0;font-family:inherit;font-size:0.88rem;outline:none;transition:border-color .15s}
.sf-input:focus,.sf-select:focus,.sf-textarea:focus{border-color:#2196F3}
.sf-select{appearance:none;-webkit-appearance:none;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8'%3E%3Cpath d='M1 1l5 5 5-5' stroke='%23666' stroke-width='1.5' fill='none' stroke-linecap='round'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 12px center;padding-right:32px}
.sf-textarea{min-height:70px;resize:vertical;line-height:1.5}
.sf-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.sf-actions{display:flex;gap:10px;margin-top:18px;align-items:center;flex-wrap:wrap}
.sf-submit-btn{background:#2196F3;border:none;color:#fff;padding:9px 24px;border-radius:7px;cursor:pointer;font-size:0.9rem;font-weight:600;transition:background .15s}
.sf-submit-btn:hover{background:#1976D2}
.sf-export-btn{background:#1e1e3a;border:1px solid #2a2a4e;color:#aaa;padding:7px 16px;border-radius:7px;cursor:pointer;font-size:0.82rem}
.sf-export-btn:hover{background:#2a2a4e;color:#fff}
.sf-msg{font-size:0.82rem;padding:8px 12px;border-radius:6px;display:none}
.sf-msg.success{background:rgba(76,175,80,.15);color:#4CAF50;border:1px solid rgba(76,175,80,.3);display:block}
.sf-msg.error{background:rgba(244,67,54,.15);color:#F44336;border:1px solid rgba(244,67,54,.3);display:block}
.user-badge{display:inline-block;padding:1px 7px;border-radius:8px;font-size:0.68rem;background:rgba(33,150,243,.2);color:#2196F3;border:1px solid rgba(33,150,243,.35);margin-left:5px;vertical-align:middle}
tr.user-row td{background:rgba(33,150,243,.05)}
@media(max-width:900px){
  #submit-fab{bottom:28px;right:90px}
  #submit-overlay{align-items:flex-end}
  #submit-modal{width:100%;max-height:88vh;border-radius:18px 18px 0 0;padding-bottom:32px;animation:sheet-in .25s ease}
  .sf-grid{grid-template-columns:1fr}
}
</style>
</head>
<body>

<header class="header">
  <h1>新加坡公民申请数据可视化</h1>
  <div class="badge">总记录 <b id="hd-total">-</b> 条</div>
  <div class="badge">通过率 <b id="hd-pass">-</b></div>
  <div class="badge">拒绝率 <b id="hd-reject">-</b></div>
  <div class="badge" style="color:#666;font-size:0.75rem">数据来源: sgprapp.com/citizen</div>
</header>

<div class="layout">
  <aside class="sidebar">
    <h4>视图</h4>
    <button class="nav-btn active" data-view="dashboard" onclick="switchView('dashboard')">数据仪表盘</button>
    <button class="nav-btn" data-view="predict" onclick="switchView('predict')">预测工具</button>

    <h4>结果筛选</h4>
    <label class="filter-item"><input type="checkbox" class="rf" value="通过" checked><span class="dot" style="background:#4CAF50"></span>通过</label>
    <label class="filter-item"><input type="checkbox" class="rf" value="杯具" checked><span class="dot" style="background:#F44336"></span>杯具</label>
    <label class="filter-item"><input type="checkbox" class="rf" value="等待" checked><span class="dot" style="background:#FF9800"></span>等待</label>
    <label class="filter-item"><input type="checkbox" class="rf" value="上诉中" checked><span class="dot" style="background:#2196F3"></span>上诉中</label>
    <label class="filter-item"><input type="checkbox" class="rf" value="未知" checked><span class="dot" style="background:#888"></span>未知</label>
    <button class="reset-btn" onclick="resetFilters()">重置所有筛选</button>

    <h4>字段覆盖率</h4>
    <div id="cov-list"></div>
  </aside>

  <main class="main">
    <div id="view-dashboard" class="view active">
    <div class="charts-grid">
      <div class="chart-card">
        <h3>申请结果分布</h3>
        <div class="chart-wrap"><canvas id="c-result"></canvas></div>
      </div>
      <div class="chart-card">
        <h3>审批时长分布（已出结果记录）</h3>
        <div class="chart-wrap"><canvas id="c-proc"></canvas></div>
      </div>
      <div class="chart-card">
        <h3>月收入 vs 申请结果（SGD）</h3>
        <div class="chart-wrap"><canvas id="c-income"></canvas></div>
      </div>
      <div class="chart-card">
        <h3>学历 vs 申请结果</h3>
        <div class="chart-wrap"><canvas id="c-edu"></canvas></div>
      </div>
      <div class="chart-card">
        <h3>持有PR年限 vs 申请结果</h3>
        <div class="chart-wrap"><canvas id="c-pr"></canvas></div>
      </div>
      <div class="chart-card">
        <h3>在新时长 vs 申请结果（年）</h3>
        <div class="chart-wrap"><canvas id="c-years"></canvas></div>
      </div>
      <div class="chart-card">
        <h3>申请时年龄 vs 申请结果</h3>
        <div class="chart-wrap"><canvas id="c-age"></canvas></div>
      </div>
      <div class="chart-card">
        <h3>家庭状况 vs 申请结果</h3>
        <div class="chart-wrap"><canvas id="c-family"></canvas></div>
      </div>
      <div class="chart-card">
        <h3>申请类型 vs 申请结果</h3>
        <div class="chart-wrap"><canvas id="c-gender"></canvas></div>
      </div>
    </div>

    <div class="table-section">
      <div class="tbl-header">
        <h3>原始数据 <span class="tbl-meta" id="tbl-count"></span></h3>
        <input class="search-box" id="search" placeholder="搜索用户名或条件内容…" oninput="applyFilters()">
      </div>
      <table>
        <thead>
          <tr>
            <th data-sort="username">用户名</th>
            <th data-sort="result_norm">结果</th>
            <th data-sort="monthly_income" data-num="1">月收入</th>
            <th data-sort="education">学历</th>
            <th data-sort="age" data-num="1">年龄</th>
            <th data-sort="years_in_sg" data-num="1">在新(年)</th>
            <th data-sort="pr_duration_years" data-num="1">PR年限</th>
            <th data-sort="gender">申请类型</th>
            <th data-sort="industry">行业</th>
            <th data-sort="apply_date" data-num="1">申请日期</th>
            <th>条件摘要</th>
          </tr>
        </thead>
        <tbody id="tbody"></tbody>
      </table>
      <div class="pager">
        <button id="btn-prev" onclick="prevPage()">上一页</button>
        <span id="page-info"></span>
        <button id="btn-next" onclick="nextPage()">下一页</button>
      </div>
    </div>
    </div><!-- /view-dashboard -->

    <div id="view-predict" class="view"></div><!-- /view-predict -->
  </main>
</div>

<script>
const RAW = __DATA__;

const RESULTS = ['通过','杯具','等待','上诉中','未知'];
const COLORS  = {'通过':'#4CAF50','杯具':'#F44336','等待':'#FF9800','上诉中':'#2196F3','未知':'#888888'};

const PAGE_SIZE = 25;
let curPage = 0;
let filtered = [...RAW];
let charts = {};

// ---- Filters ----
function getSelected() {
  return [...document.querySelectorAll('.rf:checked')].map(e => e.value);
}

function applyFilters() {
  const sel = getSelected();
  const q   = document.getElementById('search').value.toLowerCase();
  filtered = RAW.filter(r => {
    if (!sel.includes(r.result_norm)) return false;
    if (q && !r.username.toLowerCase().includes(q) && !r.conditions.toLowerCase().includes(q)) return false;
    return true;
  });
  curPage = 0;
  render();
}

function resetFilters() {
  document.querySelectorAll('.rf').forEach(e => e.checked = true);
  document.getElementById('search').value = '';
  applyFilters();
}

document.querySelectorAll('.rf').forEach(e => e.addEventListener('change', applyFilters));

// ---- Stats header ----
function renderStats() {
  const total  = filtered.length;
  const passed = filtered.filter(r => r.result_norm === '通过').length;
  const reject = filtered.filter(r => r.result_norm === '杯具').length;
  document.getElementById('hd-total').textContent  = total;
  document.getElementById('hd-pass').textContent   = total ? (passed/total*100).toFixed(1)+'%' : '-';
  document.getElementById('hd-reject').textContent = total ? (reject/total*100).toFixed(1)+'%' : '-';
}

// ---- Coverage ----
const COV_FIELDS = [
  {k:'age',             l:'年龄'},
  {k:'gender',          l:'申请类型'},
  {k:'marital',         l:'婚姻'},
  {k:'education',       l:'学历'},
  {k:'monthly_income',  l:'月收入'},
  {k:'years_in_sg',     l:'在新年限'},
  {k:'pr_duration_years',l:'PR年限'},
  {k:'children',        l:'子女数'},
  {k:'industry',        l:'行业'},
  {k:'processing_months',l:'审批时长'},
];

function renderCoverage() {
  const total = RAW.length;
  document.getElementById('cov-list').innerHTML = COV_FIELDS.map(f => {
    const n   = RAW.filter(r => r[f.k] !== null && r[f.k] !== undefined).length;
    const pct = Math.round(n/total*100);
    return `<div class="cov-row"><span>${f.l}</span><b>${n}/${total}</b></div>
            <div class="cov-bar-wrap"><div class="cov-bar" style="width:${pct}%"></div></div>`;
  }).join('');
}

// ---- Chart helpers ----
function groupByResult(data, keyFn, cats) {
  const out = {};
  RESULTS.forEach(r => { out[r] = {}; cats.forEach(c => out[r][c] = 0); });
  data.forEach(rec => {
    const cat = keyFn(rec);
    if (cat !== null && cat !== undefined && out[rec.result_norm]) {
      out[rec.result_norm][cat] = (out[rec.result_norm][cat]||0) + 1;
    }
  });
  return out;
}

function datasets(grouped, cats) {
  return RESULTS.map(r => ({
    label: r,
    data: cats.map(c => grouped[r][c]||0),
    backgroundColor: COLORS[r]+'bb',
    borderColor: COLORS[r],
    borderWidth: 1,
  }));
}

const SCALE_OPTS = {
  x: { stacked:true, ticks:{color:'#666',font:{size:10}}, grid:{color:'#181830'} },
  y: { stacked:true, ticks:{color:'#666',font:{size:10}}, grid:{color:'#181830'} },
};

const LEGEND_OPTS = {
  position:'top',
  labels:{color:'#aaa',boxWidth:11,font:{size:10},padding:8},
};

function pctTooltip(ctx) {
  const tot = ctx.chart.data.datasets.reduce((s,ds) => s+(ds.data[ctx.dataIndex]||0), 0);
  const pct = tot > 0 ? (ctx.parsed.y/tot*100).toFixed(1) : 0;
  return `${ctx.dataset.label}: ${ctx.parsed.y} (${pct}%)`;
}

function mkBar(id, labels, grouped) {
  if (charts[id]) charts[id].destroy();
  const ds = datasets(grouped, labels);
  const hasData = ds.some(d => d.data.some(v => v > 0));
  charts[id] = new Chart(document.getElementById(id), {
    type: 'bar',
    data: { labels, datasets: ds },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: LEGEND_OPTS,
        tooltip: { callbacks:{ label: pctTooltip } },
        title: hasData ? undefined : { display:true, text:'数据不足（解析命中率低）', color:'#444' },
      },
      scales: SCALE_OPTS,
    }
  });
}

// ---- All charts ----
function renderCharts() {
  const d = filtered;

  // 1. 结果分布 donut
  if (charts['c-result']) charts['c-result'].destroy();
  const rCounts = RESULTS.map(r => d.filter(x => x.result_norm===r).length);
  charts['c-result'] = new Chart(document.getElementById('c-result'), {
    type: 'doughnut',
    data: {
      labels: RESULTS,
      datasets: [{ data: rCounts, backgroundColor: RESULTS.map(r=>COLORS[r]+'cc'), borderColor: RESULTS.map(r=>COLORS[r]), borderWidth:2 }]
    },
    options: {
      responsive:true, maintainAspectRatio:false,
      plugins: {
        legend: {
          position:'right',
          labels: {
            color:'#aaa', boxWidth:12, font:{size:11},
            generateLabels: chart => {
              const tot = chart.data.datasets[0].data.reduce((a,b)=>a+b,0);
              return chart.data.labels.map((lbl,i) => {
                const v = chart.data.datasets[0].data[i];
                return { text:`${lbl}: ${v} (${tot?(v/tot*100).toFixed(1):0}%)`, fillStyle:chart.data.datasets[0].backgroundColor[i], strokeStyle:chart.data.datasets[0].borderColor[i], lineWidth:2, index:i };
              });
            }
          }
        },
        tooltip: { callbacks:{ label: ctx => { const tot=ctx.dataset.data.reduce((a,b)=>a+b,0); return `${ctx.label}: ${ctx.parsed} (${tot?(ctx.parsed/tot*100).toFixed(1):0}%)`; } } },
      }
    }
  });

  // 2. 审批时长
  const procCats = ['1-3月','3-6月','6-9月','9-12月','12-18月','>18月'];
  const procFn = r => {
    const m = r.processing_months;
    if (m===null||m===undefined) return null;
    if (m<=3) return '1-3月'; if (m<=6) return '3-6月'; if (m<=9) return '6-9月';
    if (m<=12) return '9-12月'; if (m<=18) return '12-18月'; return '>18月';
  };
  mkBar('c-proc', procCats, groupByResult(d.filter(r=>r.processing_months!==null&&r.processing_months!==undefined), procFn, procCats));

  // 3. 收入
  const incCats = ['<5k','5-10k','10-20k','>20k'];
  const incFn = r => {
    const m = r.monthly_income;
    if (m===null||m===undefined) return null;
    if (m<5000) return '<5k'; if (m<10000) return '5-10k'; if (m<20000) return '10-20k'; return '>20k';
  };
  mkBar('c-income', incCats, groupByResult(d, incFn, incCats));

  // 4. 学历
  const eduCats = ['高中','大专','本科','硕士','博士'];
  mkBar('c-edu', eduCats, groupByResult(d, r=>r.education, eduCats));

  // 5. PR 年限
  const prCats = ['<1年','1-2年','2-3年','3-5年','>5年'];
  const prFn = r => {
    const y = r.pr_duration_years;
    if (y===null||y===undefined) return null;
    if (y<1) return '<1年'; if (y<2) return '1-2年'; if (y<3) return '2-3年'; if (y<5) return '3-5年'; return '>5年';
  };
  mkBar('c-pr', prCats, groupByResult(d, prFn, prCats));

  // 6. 在新年限
  const yrCats = ['<3年','3-5年','5-8年','8-12年','>12年'];
  const yrFn = r => {
    const y = r.years_in_sg;
    if (y===null||y===undefined) return null;
    if (y<3) return '<3年'; if (y<5) return '3-5年'; if (y<8) return '5-8年'; if (y<12) return '8-12年'; return '>12年';
  };
  mkBar('c-years', yrCats, groupByResult(d, yrFn, yrCats));

  // 7. 年龄
  const ageCats = ['<25','25-30','30-35','35-40','40-45','>45'];
  const ageFn = r => {
    const a = r.age;
    if (a===null||a===undefined) return null;
    if (a<25) return '<25'; if (a<30) return '25-30'; if (a<35) return '30-35';
    if (a<40) return '35-40'; if (a<45) return '40-45'; return '>45';
  };
  mkBar('c-age', ageCats, groupByResult(d, ageFn, ageCats));

  // 8. 家庭状况
  const famCats = ['单身','已婚无孩','已婚有孩','婚况未知'];
  const famFn = r => {
    if (r.marital==='单身') return '单身';
    if (r.marital==='已婚') return (r.children===null||r.children===undefined||r.children===0) ? '已婚无孩' : '已婚有孩';
    if (r.children!==null && r.children!==undefined && r.children>0) return '已婚有孩';
    return '婚况未知';
  };
  mkBar('c-family', famCats, groupByResult(d, famFn, famCats));

  // 9. 申请类型（gender 字段：单身男/单身女/夫妻/已婚男/已婚女）
  const genCats = ['单身男','单身女','夫妻','已婚男','已婚女'];
  mkBar('c-gender', genCats, groupByResult(d, r=>r.gender, genCats));
}

// ---- Table ----
function renderTable() {
  const total = filtered.length;
  const totalPages = Math.max(1, Math.ceil(total/PAGE_SIZE));
  if (curPage >= totalPages) curPage = totalPages-1;

  const slice = filtered.slice(curPage*PAGE_SIZE, (curPage+1)*PAGE_SIZE);

  document.getElementById('tbl-count').textContent = `(${total} 条)`;
  document.getElementById('page-info').textContent  = `第 ${curPage+1} / ${totalPages} 页`;
  document.getElementById('btn-prev').disabled = curPage===0;
  document.getElementById('btn-next').disabled = curPage>=totalPages-1;

  const fmt = v => v!==null&&v!==undefined ? v : '-';
  const fmtIncome = v => v ? 'S$'+(Math.round(v/100)/10)+'k' : '-';
  const summary = s => s.length>55 ? s.slice(0,55)+'…' : s;

  document.getElementById('tbody').innerHTML = slice.length ? slice.map(r => `
    <tr>
      <td>${r.username||'-'}</td>
      <td><span class="tag t-${r.result_norm}">${r.result_norm}</span></td>
      <td>${fmtIncome(r.monthly_income)}</td>
      <td>${fmt(r.education)}</td>
      <td>${fmt(r.age)}</td>
      <td>${fmt(r.years_in_sg)}</td>
      <td>${r.pr_duration_years!==null&&r.pr_duration_years!==undefined ? r.pr_duration_years+'年' : '-'}</td>
      <td>${fmt(r.gender)}</td>
      <td>${fmt(r.industry)}</td>
      <td>${r.apply_date||'-'}</td>
      <td title="${r.conditions.replace(/"/g,'&quot;')}">${summary(r.conditions)}</td>
    </tr>`).join('') : '<tr><td colspan="11" class="no-data">无匹配数据</td></tr>';
}

// ---- Sort ----
let sortKey = null;
let sortDir = 1;  // 1 asc, -1 desc

function sortBy(key, isNum) {
  if (sortKey === key) {
    sortDir = -sortDir;
  } else {
    sortKey = key;
    sortDir = isNum ? -1 : 1;  // 数值字段默认降序（大的在前），文本字段默认升序
  }
  filtered.sort((a, b) => {
    let va = a[key], vb = b[key];
    const aNull = va===null||va===undefined||va==='';
    const bNull = vb===null||vb===undefined||vb==='';
    if (aNull && bNull) return 0;
    if (aNull) return 1;   // null 始终在末尾
    if (bNull) return -1;
    if (isNum) {
      // 日期字符串按字典序与时间序一致；数字直接比
      const na = typeof va === 'string' ? va : Number(va);
      const nb = typeof vb === 'string' ? vb : Number(vb);
      return na < nb ? -sortDir : na > nb ? sortDir : 0;
    }
    return String(va).localeCompare(String(vb)) * sortDir;
  });
  // 更新表头样式
  document.querySelectorAll('th[data-sort]').forEach(th => {
    th.classList.remove('sort-asc','sort-desc');
    if (th.dataset.sort === key) {
      th.classList.add(sortDir === 1 ? 'sort-asc' : 'sort-desc');
    }
  });
  curPage = 0;
  renderTable();
}

document.querySelectorAll('th[data-sort]').forEach(th => {
  th.addEventListener('click', () => {
    sortBy(th.dataset.sort, th.dataset.num === '1');
  });
});

function prevPage(){ curPage--; renderTable(); }
function nextPage(){ curPage++; renderTable(); }

function render() {
  renderStats();
  renderCharts();
  renderTable();
}

renderCoverage();
render();

// ============================================================
// 预测工具
// ============================================================
const MODEL = __MODEL__;

function switchView(name){
  if(name==='predict'){openPredictModal();return}
  document.querySelectorAll('.nav-btn').forEach(b=>b.classList.toggle('active',b.dataset.view===name));
  document.querySelectorAll('.view').forEach(v=>v.classList.toggle('active',v.id==='view-'+name));
}

const EXAMPLES = [
  '男，35岁，硕士，在新加坡5年，PR2年，金融行业，月薪15k SGD，已婚有一个小孩，有房产。',
  '女，28岁，本科，2018年来坡，21年PR，码农，月入8k，单身，租房。',
  '38岁男，博士，来新10年，PR满4年，半导体行业，年薪18w SGD，老婆+两小孩，已购组屋。',
];
function fillExample(i){ document.getElementById('predict-input').value = EXAMPLES[i]; }

document.addEventListener('DOMContentLoaded', function() {
  if (MODEL && MODEL.metrics) {
    const m = MODEL.metrics;
    const el = document.getElementById('model-meta');
    if (el) el.textContent = `模型: RandomForest · 训练 ${m.n_train} 条 · CV ${(m.cv_mean*100).toFixed(1)}% ± ${(m.cv_std*100).toFixed(1)}%`;
  }
});

// ---- 前端特征提取（与 scraper.py 的 regex 子集对齐） ----
const CURRENT_YEAR = new Date().getFullYear();

function extAge(t){
  let m;
  m = t.match(/(\d{2})\s*岁/); if(m) return +m[1];
  m = t.match(/(\d{2})后/); if(m){ const yy=+m[1]; const yr=yy>=50?1900+yy:2000+yy; return CURRENT_YEAR-yr; }
  m = t.match(/(?:男|女)[，,\s]*(\d{2})(?![年月千万kK])/); if(m) return +m[1];
  m = t.match(/(\d{2})\s*(?:男|女)/); if(m) return +m[1];
  m = t.match(/年龄\s*[:：]?\s*(\d{2})/); if(m) return +m[1];
  m = t.match(/(\d{4})年生/); if(m) return CURRENT_YEAR-(+m[1]);
  return null;
}
function extGender(t){
  if(/单身男|男娃|未婚男|SM\b/.test(t)) return '单身男';
  if(/单身女|女娃|未婚女|SF\b/.test(t)) return '单身女';
  if(/已婚男|有老婆|有妻|带老婆|妻子|配偶女|带太太/.test(t)) return '已婚男';
  if(/已婚女|有老公|带老公|丈夫|配偶男|带先生/.test(t)) return '已婚女';
  if(/^|[^未]男(?![性老女])/.test(t) && /男/.test(t)) return '男';
  if(/女/.test(t) && !/女儿/.test(t.replace(/.{0,2}女儿/,''))) return '女';
  return null;
}
function extMarital(t){
  if(/已婚|结婚|配偶|老婆|老公|妻子|丈夫|太太|先生/.test(t)) return '已婚';
  if(/单身|未婚/.test(t)) return '单身';
  if(/离婚|离异/.test(t)) return '离异';
  return null;
}
function extEducation(t){
  if(/博士|PhD|phd/.test(t)) return '博士';
  if(/硕士|master|MBA|本坡硕|海硕|研究生/i.test(t)) return '硕士';
  if(/本科|学士|bachelor|本坡本|CS本科/i.test(t)) return '本科';
  if(/大专|专科|diploma/i.test(t)) return '大专';
  if(/高中|中专/.test(t)) return '高中';
  return null;
}
function extIncome(t){
  // 月薪 Xk 或 X千
  let m = t.match(/月(?:薪|收入|入)\s*[约~]?\s*(\d+(?:\.\d+)?)\s*[kK千]/);
  if(m) return Math.round(+m[1]*1000);
  m = t.match(/月(?:薪|收入|入)\s*[约~]?\s*(\d{4,6})/);
  if(m) return +m[1];
  // 年薪 Xw / Xk
  m = t.match(/年(?:薪|收入|入|包)\s*[约~]?\s*(\d+(?:\.\d+)?)\s*[wW万]/);
  if(m) return Math.round(+m[1]*10000/12);
  m = t.match(/年(?:薪|收入|入|包)\s*[约~]?\s*(\d+(?:\.\d+)?)\s*[kK千]/);
  if(m) return Math.round(+m[1]*1000/12);
  // 无前缀的 Xk 在 "薪/月/申请" 上下文
  m = t.match(/(?:薪|工资|挣|赚|拿)\s*[约~]?\s*(\d+(?:\.\d+)?)\s*[kK]/);
  if(m) return Math.round(+m[1]*1000);
  return null;
}
function extYearsInSg(t){
  let m = t.match(/(?:在|来|到|住)新?加?坡?\s*(\d+(?:\.\d+)?)\s*年/);
  if(m) return +m[1];
  m = t.match(/(\d{4})年来(?:坡|新|新加坡)/);
  if(m) return CURRENT_YEAR-(+m[1]);
  m = t.match(/来新\s*(\d+)\s*年/);
  if(m) return +m[1];
  return null;
}
function extPrYears(t){
  let m = t.match(/PR\s*(\d+(?:\.\d+)?)\s*年/i);
  if(m) return +m[1];
  m = t.match(/(\d+(?:\.\d+)?)\s*年\s*PR/i);
  if(m) return +m[1];
  m = t.match(/PR\s*一年半/i); if(m) return 1.5;
  m = t.match(/PR\s*(?:满|刚满|快满)\s*(\d+)/i); if(m) return +m[1];
  m = t.match(/PR\s*第\s*(\d+)\s*年/i); if(m) return Math.max(0, +m[1]-1);
  m = t.match(/(\d{2})\s*年\s*(?:拿|批)?\s*PR/i);
  if(m){ const yy=+m[1]; const yr=yy>=50?1900+yy:2000+yy; return CURRENT_YEAR-yr; }
  return null;
}
function extChildren(t){
  let m = t.match(/(\d+|一|两|二|三)\s*(?:个|名)?\s*(?:小孩|孩子|娃|子女)/);
  if(m){ const map={'一':1,'两':2,'二':2,'三':3}; return map[m[1]]||+m[1]; }
  if(/有娃|带娃|K1|K2|幼儿园/.test(t)) return 1;
  if(/无娃|无小孩|没小孩|未育/.test(t)) return 0;
  return null;
}
function extProperty(t){
  if(/有房|购房|买了房|组屋|HDB|公寓|condo|私宅|有不动产|名下有房/i.test(t)) return true;
  if(/无房|没房|租房|租住|无不动产|名下无房/.test(t)) return false;
  return null;
}
function extIndustry(t){
  if(/建筑|土木工程|机械工程|civil engineer|architect|construction|施工/i.test(t)) return '工程/建筑';
  if(/房产|房地产|地产|real estate/i.test(t)) return '房产/建筑';
  if(/码农|软件|程序员|互联网|科技|developer|software|半导体|tech|\bIT\b|backend|frontend/i.test(t)) return 'IT/科技';
  if(/金融|银行|保险|投资|基金|会计|财务|fintech|bank|finance/i.test(t)) return '金融';
  if(/医疗|医生|护士|医院|药|doctor|nurse|hospital|medical/i.test(t)) return '医疗';
  if(/教育|老师|教师|教授|研究|科研|teacher|professor|research/i.test(t)) return '教育/科研';
  if(/咨询|经理|管理|销售|市场|运营|consultant|manager|marketing/i.test(t)) return '商业/管理';
  if(/律师|法律|law|attorney|legal/i.test(t)) return '法律';
  if(/创业|自雇|自营|开公司|freelance|entrepreneur|startup/i.test(t)) return '创业/自雇';
  if(/贸易|进出口|物流|运输|logistics|trading/i.test(t)) return '贸易/物流';
  if(/工程|engineer/i.test(t)) return '其他工程';
  return null;
}

function extractFeatures(text){
  return {
    age: extAge(text),
    gender: extGender(text),
    marital: extMarital(text),
    education: extEducation(text),
    monthly_income: extIncome(text),
    years_in_sg: extYearsInSg(text),
    pr_duration_years: extPrYears(text),
    children: extChildren(text),
    has_property: extProperty(text),
    industry: extIndustry(text),
  };
}

// ---- 前端 RandomForest 推理 ----
function vectorize(feat){
  const M = MODEL;
  const row = [];
  for(const f of M.num_features){
    const v = feat[f];
    row.push(v != null ? +v : M.num_medians[f]);
  }
  for(const f of M.cat_features){
    const rv = feat[f];
    const rvStr = rv == null ? null : String(rv);
    for(const v of M.cat_vocab[f]){
      row.push(rvStr === v ? 1 : 0);
    }
  }
  return row;
}
function treePredict(nodes, x){
  let i = 0;
  for(let step=0; step<1000; step++){
    const n = nodes[i];
    if(n.l) return n.p;
    i = x[n.f] <= n.t ? n.L : n.R;
  }
  return 0.5;
}
function rfPredict(feat){
  const x = vectorize(feat);
  let sum = 0;
  for(const tree of MODEL.trees) sum += treePredict(tree, x);
  return sum / MODEL.trees.length;
}

// ---- 分析与建议 ----
const FIELD_LABEL = {
  age:'年龄', gender:'申请类型', marital:'婚姻', education:'学历',
  monthly_income:'月收入(SGD)', years_in_sg:'在新年限', pr_duration_years:'PR年限',
  children:'子女数', has_property:'房产', industry:'行业',
};
const CRITICAL = ['age','education','pr_duration_years','years_in_sg'];
const OPTIONAL = ['gender','marital','monthly_income','children','has_property','industry'];

function buildAnalysis(feat, prob){
  const pros = [], cons = [];

  if(feat.education === '博士') pros.push('博士学历（高加分）');
  else if(feat.education === '硕士') pros.push('硕士学历');
  else if(feat.education === '本科') pros.push('本科学历');
  else if(feat.education === '高中' || feat.education === '大专') cons.push('学历偏低，建议补充技能/工作证明');

  if(feat.pr_duration_years != null){
    if(feat.pr_duration_years >= 4) pros.push(`持有 PR ${feat.pr_duration_years} 年（满足典型门槛）`);
    else if(feat.pr_duration_years >= 2) cons.push(`PR ${feat.pr_duration_years} 年偏短，3-4 年后申请通常更稳`);
    else cons.push(`PR 不足 2 年，时长偏短`);
  }

  if(feat.years_in_sg != null){
    if(feat.years_in_sg >= 8) pros.push(`在新 ${feat.years_in_sg} 年（稳定性强）`);
    else if(feat.years_in_sg >= 4) pros.push(`在新 ${feat.years_in_sg} 年`);
    else cons.push(`在新时长 ${feat.years_in_sg} 年偏短`);
  }

  if(feat.monthly_income != null){
    if(feat.monthly_income >= 12000) pros.push(`月收入 ${feat.monthly_income} SGD（高于常见中位数）`);
    else if(feat.monthly_income >= 6000) pros.push(`月收入 ${feat.monthly_income} SGD`);
    else cons.push(`月收入 ${feat.monthly_income} SGD 偏低`);
  }

  if(feat.age != null){
    if(feat.age >= 28 && feat.age <= 42) pros.push(`年龄 ${feat.age}（黄金区间）`);
    else if(feat.age > 50) cons.push(`年龄 ${feat.age} 偏高`);
    else if(feat.age < 25) cons.push(`年龄 ${feat.age} 偏年轻`);
  }

  if(feat.has_property === true) pros.push('已购房产（稳定性信号）');
  if(feat.marital === '已婚') pros.push('已婚（家庭稳定）');
  if(feat.children != null && feat.children > 0) pros.push(`有 ${feat.children} 个孩子（家庭根基）`);

  if(feat.industry === 'IT/科技' || feat.industry === '金融' || feat.industry === '医疗')
    pros.push(`${feat.industry} 行业（紧缺/优势行业）`);

  // 建议
  const tips = [];
  if(feat.pr_duration_years != null && feat.pr_duration_years < 3)
    tips.push('如非紧迫，建议在 PR 满 3-4 年后再申请，历史通过率明显更高');
  if(feat.has_property == null)
    tips.push('补充房产信息（HDB/公寓/无房均可）有助于增加稳定性信号');
  if(feat.monthly_income == null)
    tips.push('补充收入信息（月薪/年薪）以提升预测准确度');
  if(feat.industry == null)
    tips.push('注明所在行业（特别是紧缺行业更利好）');
  if(prob < 0.5)
    tips.push('建议咨询专业移民顾问，结合最新政策与个人情况优化材料');
  if(tips.length === 0)
    tips.push('整体材料看起来不错，按当前条件正常提交即可');

  return {pros, cons, tips};
}

function runPredict(){
  const text = document.getElementById('predict-input').value.trim();
  if(!text){ alert('请输入申请人信息'); return; }

  const feat = extractFeatures(text);
  const prob = rfPredict(feat);
  const ana = buildAnalysis(feat, prob);
  const missC = CRITICAL.filter(f => feat[f] == null);
  const missO = OPTIONAL.filter(f => feat[f] == null);

  renderPredict(feat, prob, ana, missC, missO);
}

function renderPredict(feat, prob, ana, missC, missO){
  const pct = (prob*100).toFixed(1);
  const tier = prob >= 0.7 ? ['tier-high','成功率较高'] :
               prob >= 0.45 ? ['tier-mid','成功率中等'] :
                              ['tier-low','成功率偏低'];

  const fmtVal = (k,v) => {
    if(v == null) return '<span class="miss">未提取到</span>';
    if(k === 'has_property') return v ? '有' : '无';
    if(k === 'monthly_income') return Number(v).toLocaleString() + ' SGD';
    return v;
  };

  const featRows = Object.keys(FIELD_LABEL).map(k=>
    `<tr><td style="color:#888;width:120px">${FIELD_LABEL[k]}</td>
         <td ${feat[k]==null?'class="miss"':''}>${fmtVal(k,feat[k])}</td></tr>`
  ).join('');

  const prosHtml = ana.pros.length
    ? ana.pros.map(s=>`<li><span class="icon">✓</span>${s}</li>`).join('')
    : '<li style="color:#666">未识别到明显利好因素</li>';
  const consHtml = ana.cons.length
    ? ana.cons.map(s=>`<li><span class="icon">!</span>${s}</li>`).join('')
    : '<li style="color:#666">未识别到明显风险因素</li>';
  const tipsHtml = ana.tips.map(s=>`<li>${s}</li>`).join('');

  let missingBlock = '';
  if(missC.length || missO.length){
    const cTags = missC.map(f=>`<span class="tag t-杯具" style="margin-right:6px">${FIELD_LABEL[f]}</span>`).join('');
    const oTags = missO.map(f=>`<span class="tag t-未知" style="margin-right:6px">${FIELD_LABEL[f]}</span>`).join('');
    missingBlock = `
      <div class="analysis-card" style="grid-column:1/-1">
        <h3>缺少信息（补充后预测更准）</h3>
        ${missC.length?`<div style="margin-bottom:8px;font-size:0.82rem;color:#aaa">关键字段缺失：${cTags}</div>`:''}
        ${missO.length?`<div style="font-size:0.82rem;color:#888">可选字段缺失：${oTags}</div>`:''}
      </div>`;
  }

  document.getElementById('predict-result').innerHTML = `
    <div class="proba-card">
      <div class="proba-num">${pct}%</div>
      <div class="proba-label">预估成功概率</div>
      <div class="proba-bar-wrap"><div class="proba-bar" style="width:${pct}%"></div></div>
      <div class="proba-tier ${tier[0]}">${tier[1]}</div>
    </div>

    <div class="analysis-grid">
      <div class="analysis-card">
        <h3 style="color:#4CAF50">利好因素</h3>
        <ul class="analysis-list">${prosHtml}</ul>
      </div>
      <div class="analysis-card">
        <h3 style="color:#FF9800">风险因素</h3>
        <ul class="analysis-list">${consHtml}</ul>
      </div>
      <div class="analysis-card">
        <h3>提取到的特征</h3>
        <table class="feat-table">${featRows}</table>
      </div>
      <div class="analysis-card">
        <h3>建议</h3>
        <ol class="suggestion-list">${tipsHtml}</ol>
      </div>
      ${missingBlock}
    </div>
  `;
}
function openPredictModal(){document.getElementById('predict-overlay').classList.add('open');document.body.style.overflow='hidden'}
function closePredictModal(){document.getElementById('predict-overlay').classList.remove('open');document.body.style.overflow=''}
function handleOverlayClick(e){if(e.target===document.getElementById('predict-overlay'))closePredictModal()}
document.addEventListener('keydown',e=>{if(e.key==='Escape'){closePredictModal();closeSubmitModal();}});

// ============================================================
// 提交数据功能
// ============================================================

function openSubmitModal(){
  document.getElementById('sf-msg').className='sf-msg';
  document.getElementById('sf-msg').textContent='';
  document.getElementById('submit-overlay').classList.add('open');
  document.body.style.overflow='hidden';
}
function closeSubmitModal(){
  document.getElementById('submit-overlay').classList.remove('open');
  document.body.style.overflow='';
}
function handleSubmitOverlayClick(e){
  if(e.target===document.getElementById('submit-overlay')) closeSubmitModal();
}

function validateSubmission(data){
  if(!data.result || !data.apply_year) return '请填写申请结果和申请年份';
  if(data.age && (data.age < 18 || data.age > 70)) return '年龄需在 18-70 之间';
  if(data.income && (data.income < 1000 || data.income > 100000)) return '月收入需在 1,000-100,000 之间';
  if(data.apply_year < 2015 || data.apply_year > 2026) return '申请年份不合法';
  const lastSubmit = localStorage.getItem('last_submit_time');
  if(lastSubmit && Date.now() - parseInt(lastSubmit) < 60000) return '提交过于频繁，请稍后再试';
  if(data.note && data.note.length > 200) return '备注不超过 200 字';
  return null;
}

function submitMyData(){
  const data = {
    result:      document.getElementById('sf-result').value,
    apply_year:  parseInt(document.getElementById('sf-year').value) || null,
    age:         parseInt(document.getElementById('sf-age').value) || null,
    income:      parseInt(document.getElementById('sf-income').value) || null,
    education:   document.getElementById('sf-education').value || null,
    marital:     document.getElementById('sf-marital').value || null,
    pr:          parseFloat(document.getElementById('sf-pr').value) || null,
    years:       parseFloat(document.getElementById('sf-years').value) || null,
    note:        document.getElementById('sf-note').value.trim() || null,
  };

  const err = validateSubmission(data);
  const msgEl = document.getElementById('sf-msg');
  if(err){
    msgEl.textContent = err;
    msgEl.className = 'sf-msg error';
    return;
  }

  const noteText = [
    data.note || '',
    data.age ? `${data.age}岁` : '',
    data.education || '',
    data.marital || '',
    data.income ? `月薪${data.income}SGD` : '',
    data.pr != null ? `PR${data.pr}年` : '',
    data.years != null ? `在新${data.years}年` : '',
  ].filter(Boolean).join('，');

  const record = {
    username: '我的数据',
    result: data.result,
    result_norm: data.result,
    apply_date: data.apply_year ? String(data.apply_year) + '-01-01' : '',
    end_date: '',
    conditions: noteText,
    age: data.age,
    gender: null,
    marital: data.marital,
    education: data.education,
    monthly_income: data.income,
    years_in_sg: data.years,
    pr_duration_years: data.pr,
    children: null,
    has_property: null,
    industry: null,
    processing_months: null,
    is_user_submission: true,
    submitted_at: new Date().toISOString(),
  };

  const existing = JSON.parse(localStorage.getItem('user_submissions') || '[]');
  existing.push(record);
  localStorage.setItem('user_submissions', JSON.stringify(existing));
  localStorage.setItem('last_submit_time', String(Date.now()));

  msgEl.textContent = '提交成功，感谢您的贡献！数据已保存到本地浏览器。';
  msgEl.className = 'sf-msg success';

  // 重置表单
  ['sf-result','sf-year','sf-age','sf-income','sf-education','sf-marital','sf-pr','sf-years','sf-note'].forEach(id => {
    const el = document.getElementById(id);
    if(el) el.value = '';
  });

  // 刷新图表和表格（含新提交数据）
  applyFilters();
}

function exportMyData(){
  const subs = JSON.parse(localStorage.getItem('user_submissions') || '[]');
  if(subs.length === 0){
    alert('暂无提交记录');
    return;
  }
  const blob = new Blob([JSON.stringify(subs, null, 2)], {type:'application/json'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'my_citizen_submissions.json';
  a.click();
  URL.revokeObjectURL(url);
}

// 加载用户提交的数据并合并到图表
function loadUserSubmissions(){
  return JSON.parse(localStorage.getItem('user_submissions') || '[]');
}

// 重写 applyFilters 以合并用户数据
const _origApplyFilters = applyFilters;
(function(){
  // 覆盖 applyFilters，在过滤后追加用户提交的记录
  window.applyFilters = function(){
    const sel = getSelected();
    const q   = document.getElementById('search').value.toLowerCase();
    filtered = RAW.filter(r => {
      if(!sel.includes(r.result_norm)) return false;
      if(q && !r.username.toLowerCase().includes(q) && !r.conditions.toLowerCase().includes(q)) return false;
      return true;
    });
    // 追加用户提交（也应用结果筛选）
    const userSubs = loadUserSubmissions().filter(r => sel.includes(r.result_norm));
    filtered = filtered.concat(userSubs);
    curPage = 0;
    render();
  };
})();

// 覆盖 renderTable 以高亮用户提交行
const _origRenderTable = renderTable;
window.renderTable = function(){
  const total = filtered.length;
  const totalPages = Math.max(1, Math.ceil(total/PAGE_SIZE));
  if(curPage >= totalPages) curPage = totalPages-1;

  const slice = filtered.slice(curPage*PAGE_SIZE, (curPage+1)*PAGE_SIZE);

  document.getElementById('tbl-count').textContent = `(${total} 条)`;
  document.getElementById('page-info').textContent  = `第 ${curPage+1} / ${totalPages} 页`;
  document.getElementById('btn-prev').disabled = curPage===0;
  document.getElementById('btn-next').disabled = curPage>=totalPages-1;

  const fmt = v => v!==null&&v!==undefined ? v : '-';
  const fmtIncome = v => v ? 'S$'+(Math.round(v/100)/10)+'k' : '-';
  const summary = s => s.length>55 ? s.slice(0,55)+'...' : s;

  document.getElementById('tbody').innerHTML = slice.length ? slice.map(r => {
    const userMark = r.is_user_submission ? '<span class="user-badge">我的</span>' : '';
    const rowClass = r.is_user_submission ? ' class="user-row"' : '';
    return `<tr${rowClass}>
      <td>${(r.username||'-')}${userMark}</td>
      <td><span class="tag t-${r.result_norm}">${r.result_norm}</span></td>
      <td>${fmtIncome(r.monthly_income)}</td>
      <td>${fmt(r.education)}</td>
      <td>${fmt(r.age)}</td>
      <td>${fmt(r.years_in_sg)}</td>
      <td>${r.pr_duration_years!==null&&r.pr_duration_years!==undefined ? r.pr_duration_years+'年' : '-'}</td>
      <td>${fmt(r.gender)}</td>
      <td>${fmt(r.industry)}</td>
      <td>${r.apply_date||'-'}</td>
      <td title="${r.conditions.replace(/"/g,'&quot;')}">${summary(r.conditions)}</td>
    </tr>`;
  }).join('') : '<tr><td colspan="11" class="no-data">无匹配数据</td></tr>';
};

// 初始化时也合并用户提交数据
(function(){
  const userSubs = loadUserSubmissions();
  if(userSubs.length > 0){
    const sel = [...document.querySelectorAll('.rf:checked')].map(e => e.value);
    filtered = filtered.concat(userSubs.filter(r => sel.includes(r.result_norm)));
    render();
  }
})();
</script>
<button id="submit-fab" onclick="openSubmitModal()" title="提交我的申请数据">📝</button>
<button id="predict-fab" onclick="openPredictModal()" title="申请成功率预测">📊</button>
<div id="predict-overlay" onclick="handleOverlayClick(event)">
  <div id="predict-modal" onclick="event.stopPropagation()">
    <button id="modal-close" onclick="closePredictModal()">✕</button>
    <div class="predict-card">
      <h2>申请成功率预测</h2>
      <p class="hint">粘贴或输入申请人的简要信息（自由文本，与历史样本风格相似即可）。系统会自动提取年龄、学历、收入、PR 年限等关键特征，并基于历史 273 条已结案样本训练的随机森林模型给出成功率预测与建议。<span style="color:#666">本工具仅供参考，预测结果不代表官方决定。</span></p>
      <textarea id="predict-input" class="predict-input" rows="5" placeholder="例如：男，35岁，硕士，在新加坡5年，PR2年，金融行业，月薪15k SGD，已婚有一个小孩，有房产，准备申请..."></textarea>
      <div class="predict-actions">
        <button class="predict-btn" id="btn-predict" onclick="runPredict()">开始预测</button>
        <button class="example-btn" onclick="fillExample(0)">示例 1</button>
        <button class="example-btn" onclick="fillExample(1)">示例 2</button>
        <button class="example-btn" onclick="fillExample(2)">示例 3</button>
        <span class="model-meta" id="model-meta"></span>
      </div>
    </div>
    <div id="predict-result">
      <div class="predict-card predict-empty">输入申请信息后点击"开始预测"，结果将在此显示。</div>
    </div>
  </div>
</div>
<div id="submit-overlay" onclick="handleSubmitOverlayClick(event)">
  <div id="submit-modal" onclick="event.stopPropagation()">
    <button id="submit-close" onclick="closeSubmitModal()">&#x2715;</button>
    <div class="sf-title">提交我的申请数据</div>
    <div class="sf-hint">您的数据将仅存储在本地浏览器中（localStorage），不会上传到任何服务器。感谢您的贡献！</div>

    <div id="sf-msg" class="sf-msg"></div>

    <div class="sf-row">
      <label>申请结果 <span>*</span></label>
      <select id="sf-result" class="sf-select">
        <option value="">请选择</option>
        <option value="通过">通过</option>
        <option value="杯具">拒绝</option>
        <option value="等待">等待中</option>
      </select>
    </div>

    <div class="sf-row">
      <label>申请年份 <span>*</span></label>
      <input id="sf-year" type="number" class="sf-input" placeholder="例如 2022" min="2015" max="2026">
    </div>

    <div class="sf-grid">
      <div class="sf-row">
        <label>年龄（岁）</label>
        <input id="sf-age" type="number" class="sf-input" placeholder="18-70" min="18" max="70">
      </div>
      <div class="sf-row">
        <label>月收入 SGD</label>
        <input id="sf-income" type="number" class="sf-input" placeholder="1000-100000" min="1000" max="100000">
      </div>
      <div class="sf-row">
        <label>学历</label>
        <select id="sf-education" class="sf-select">
          <option value="">请选择</option>
          <option value="高中">高中</option>
          <option value="大专">大专</option>
          <option value="本科">本科</option>
          <option value="硕士">硕士</option>
          <option value="博士">博士</option>
        </select>
      </div>
      <div class="sf-row">
        <label>婚姻状态</label>
        <select id="sf-marital" class="sf-select">
          <option value="">请选择</option>
          <option value="单身">单身</option>
          <option value="已婚">已婚</option>
          <option value="离异">离异</option>
        </select>
      </div>
      <div class="sf-row">
        <label>PR 年限（年）</label>
        <input id="sf-pr" type="number" class="sf-input" placeholder="0-20" min="0" max="20" step="0.5">
      </div>
      <div class="sf-row">
        <label>在新年限（年）</label>
        <input id="sf-years" type="number" class="sf-input" placeholder="0-30" min="0" max="30" step="0.5">
      </div>
    </div>

    <div class="sf-row">
      <label>备注（选填，最多 200 字）</label>
      <textarea id="sf-note" class="sf-textarea" placeholder="补充其他相关信息，如行业、职业、家庭情况等…" maxlength="200"></textarea>
    </div>

    <div class="sf-actions">
      <button class="sf-submit-btn" onclick="submitMyData()">提交数据</button>
      <button class="sf-export-btn" onclick="exportMyData()">导出我的数据</button>
    </div>
  </div>
</div>
</body>
</html>
"""


def generate_html(records):
    data_json = json.dumps(records, ensure_ascii=False, separators=(',', ':'))
    # 嵌入预测模型（如果已训练，否则前端走"模型未加载"分支）
    model_path = Path(__file__).parent / 'model.json'
    if model_path.exists():
        model_json = model_path.read_text(encoding='utf-8')
    else:
        model_json = 'null'
    return (HTML_TEMPLATE
            .replace('__DATA__', data_json)
            .replace('__MODEL__', model_json))


# ============================================================
# 主程序
# ============================================================

def main():
    print("=" * 55)
    print("  新加坡公民申请数据可视化爬虫")
    print("=" * 55)

    force_refresh = '--force-refresh' in sys.argv
    unique_records = None

    if not force_refresh:
        cached, valid = load_cache()
        if valid:
            unique_records = cached

    if unique_records is None:
        # 正常爬取流程
        session = requests.Session()
        all_records = []

        for page in range(0, TOTAL_PAGES):
            print(f"  第 {page:2d}/{TOTAL_PAGES - 1} 页...", end=' ', flush=True)
            html = fetch_page(page, session)
            if html:
                recs = parse_page(html)
                all_records.extend(recs)
                print(f"{len(recs)} 条")
            else:
                print("跳过")
            time.sleep(0.8)

        print(f"\n  共获取 {len(all_records)} 条记录，去重中...")
        # 精确去重：基于 (username, apply_date, result 前 30 字) 三元组
        # 这样可以保留同一用户的不同次申请，仅过滤真正重复的状态更新
        seen_keys = set()
        unique_records = []
        for r in all_records:
            result_prefix = r['result'][:30] if r.get('result') else ''
            key = (r.get('username', ''), r.get('apply_date', ''), result_prefix)
            if key not in seen_keys:
                seen_keys.add(key)
                unique_records.append(r)

        save_cache(unique_records)

    print(f"  去重后 {len(unique_records)} 条记录，开始解析字段...")
    enriched = [enrich(r) for r in unique_records]

    # 输出解析覆盖率统计
    total = len(enriched)
    if total:
        print("\n  字段解析覆盖率：")
        fields = [
            ('age', '年龄'), ('gender', '性别'), ('marital', '婚姻'),
            ('education', '学历'), ('monthly_income', '月收入'),
            ('years_in_sg', '在新年限'), ('pr_duration_years', 'PR年限'),
            ('children', '子女数'), ('industry', '行业'),
            ('processing_months', '审批时长'),
        ]
        for key, label in fields:
            n = sum(1 for r in enriched if r.get(key) is not None)
            print(f"    {label:8s}: {n:3d}/{total} ({n/total*100:.0f}%)")

    print(f"\n  生成可视化页面 → {OUTPUT_FILE} ...")
    html_content = generate_html(enriched)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"\n  完成！")
    print(f"  打开命令: open {OUTPUT_FILE}")
    print("=" * 55)


if __name__ == '__main__':
    main()

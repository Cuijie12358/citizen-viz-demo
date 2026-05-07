"""
训练新加坡公民申请成功率预测模型

使用方法：
    python3 context/train_model.py

输入：context/citizen_viz.html 中嵌入的 records 数据（自动提取）
输出：
    - context/model.pkl       Python 端模型（供 Flask 服务使用）
    - context/model.json      前端 JS 推理用的树结构（嵌入 HTML）
    - context/model_meta.json 特征名/类目编码/统计信息

数据预处理：
    - 目标：result_norm == "通过" → 1，其他 → 0（剔除"等待"和"未知"，因为标签未知）
    - 数值特征缺失：用中位数填充
    - 类别特征缺失：用 "_unknown" 占位
    - 类别编码：one-hot
"""
import json
import re
import pickle
from pathlib import Path
from collections import Counter

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.metrics import classification_report

ROOT = Path(__file__).parent
HTML = ROOT / "citizen_viz.html"
MODEL_PKL = ROOT / "model.pkl"
MODEL_JSON = ROOT / "model.json"
MODEL_META = ROOT / "model_meta.json"

NUM_FEATURES = [
    'age', 'monthly_income', 'years_in_sg',
    'pr_duration_years', 'children',
]
CAT_FEATURES = [
    'gender', 'marital', 'education', 'industry', 'has_property',
]


def load_records():
    """从 citizen_viz.html 中提取 RAW = [...] 数据"""
    text = HTML.read_text(encoding='utf-8')
    m = re.search(r'const\s+RAW\s*=\s*(\[.*?\]);', text, re.S)
    if not m:
        raise RuntimeError("无法在 citizen_viz.html 中找到 RAW 数据块")
    return json.loads(m.group(1))


def filter_labeled(records):
    """只保留有明确通过/拒绝结果的记录"""
    out = []
    for r in records:
        rn = r.get('result_norm')
        if rn == '通过':
            r['_label'] = 1
            out.append(r)
        elif rn == '杯具':  # 拒绝
            r['_label'] = 0
            out.append(r)
    return out


def build_feature_matrix(records, cat_vocab=None):
    """
    把 records 转成数值矩阵。
    返回 (X, y, feature_names, cat_vocab, num_medians)
    cat_vocab: {field: [val1, val2, ...]} 用于 one-hot 列顺序
    """
    # 数值列：先收集，算中位数
    num_medians = {}
    for f in NUM_FEATURES:
        vals = [r.get(f) for r in records if r.get(f) is not None]
        num_medians[f] = float(np.median(vals)) if vals else 0.0

    # 类别词表
    if cat_vocab is None:
        cat_vocab = {}
        for f in CAT_FEATURES:
            vals = [r.get(f) for r in records if r.get(f) is not None]
            # has_property 是布尔，转为字符串
            uniq = sorted({str(v) for v in vals})
            cat_vocab[f] = uniq

    feature_names = list(NUM_FEATURES)
    for f in CAT_FEATURES:
        for v in cat_vocab[f]:
            feature_names.append(f"{f}={v}")

    X = []
    y = []
    for r in records:
        row = []
        for f in NUM_FEATURES:
            v = r.get(f)
            row.append(float(v) if v is not None else num_medians[f])
        for f in CAT_FEATURES:
            rv = r.get(f)
            rv_str = str(rv) if rv is not None else None
            for v in cat_vocab[f]:
                row.append(1.0 if rv_str == v else 0.0)
        X.append(row)
        if '_label' in r:
            y.append(r['_label'])
    return np.array(X), np.array(y) if y else None, feature_names, cat_vocab, num_medians


def export_tree(tree):
    """sklearn DecisionTree → 前端可消费的紧凑结构"""
    t = tree.tree_
    nodes = []
    for i in range(t.node_count):
        if t.children_left[i] == -1:
            # 叶子：记录类别概率（class 1 概率）
            value = t.value[i][0]
            total = float(value.sum())
            p1 = float(value[1] / total) if total > 0 and len(value) > 1 else 0.0
            nodes.append({'l': True, 'p': p1})
        else:
            nodes.append({
                'l': False,
                'f': int(t.feature[i]),
                't': float(t.threshold[i]),
                'L': int(t.children_left[i]),
                'R': int(t.children_right[i]),
            })
    return nodes


def main():
    print("=" * 60)
    print("  公民申请成功率预测模型 - 训练")
    print("=" * 60)

    records = load_records()
    print(f"  原始记录: {len(records)}")

    labeled = filter_labeled(records)
    print(f"  有标签记录: {len(labeled)}（剔除等待/未知）")
    counter = Counter(r['_label'] for r in labeled)
    print(f"  通过 / 拒绝: {counter[1]} / {counter[0]}")

    if len(labeled) < 30:
        raise RuntimeError("有标签数据太少，无法训练")

    X, y, feature_names, cat_vocab, num_medians = build_feature_matrix(labeled)
    print(f"  特征维度: {X.shape[1]}（{len(NUM_FEATURES)} 数值 + {X.shape[1]-len(NUM_FEATURES)} one-hot）")

    # 训练 / 评估
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    model = RandomForestClassifier(
        n_estimators=120, max_depth=8, min_samples_leaf=3,
        random_state=42, class_weight='balanced',
    )
    model.fit(Xtr, ytr)

    train_acc = model.score(Xtr, ytr)
    test_acc = model.score(Xte, yte)
    cv_scores = cross_val_score(model, X, y, cv=5)
    print(f"\n  训练集准确率: {train_acc:.3f}")
    print(f"  测试集准确率: {test_acc:.3f}")
    print(f"  5-折交叉验证: {cv_scores.mean():.3f} ± {cv_scores.std():.3f}")
    print(f"\n  分类报告（测试集）:")
    print(classification_report(yte, model.predict(Xte), target_names=['拒绝', '通过']))

    # 在全量数据上重新训练（用于发布）
    model.fit(X, y)

    # 特征重要度
    importance = sorted(
        zip(feature_names, model.feature_importances_),
        key=lambda x: -x[1]
    )
    print("  Top 10 特征重要度：")
    for name, imp in importance[:10]:
        bar = '█' * int(imp * 100)
        print(f"    {name:<32s} {imp:.4f} {bar}")

    # 保存 pkl（Flask 服务用）
    with open(MODEL_PKL, 'wb') as f:
        pickle.dump({
            'model': model,
            'feature_names': feature_names,
            'cat_vocab': cat_vocab,
            'num_medians': num_medians,
            'num_features': NUM_FEATURES,
            'cat_features': CAT_FEATURES,
        }, f)
    print(f"\n  saved {MODEL_PKL.name} ({MODEL_PKL.stat().st_size // 1024} KB)")

    # 导出 JSON 供前端推理
    trees = [export_tree(est) for est in model.estimators_]
    model_json = {
        'trees': trees,
        'n_features': X.shape[1],
        'feature_names': feature_names,
        'num_features': NUM_FEATURES,
        'cat_features': CAT_FEATURES,
        'cat_vocab': cat_vocab,
        'num_medians': num_medians,
        'feature_importance': dict(importance),
        'metrics': {
            'train_acc': float(train_acc),
            'test_acc': float(test_acc),
            'cv_mean': float(cv_scores.mean()),
            'cv_std': float(cv_scores.std()),
            'n_train': int(len(labeled)),
            'n_pass': int(counter[1]),
            'n_reject': int(counter[0]),
        },
    }
    with open(MODEL_JSON, 'w', encoding='utf-8') as f:
        json.dump(model_json, f, ensure_ascii=False, separators=(',', ':'))
    print(f"  saved {MODEL_JSON.name} ({MODEL_JSON.stat().st_size // 1024} KB)")

    # 元信息（人类可读）
    with open(MODEL_META, 'w', encoding='utf-8') as f:
        json.dump({
            'metrics': model_json['metrics'],
            'top_features': [(n, float(imp)) for n, imp in importance[:20]],
            'cat_vocab': cat_vocab,
            'num_medians': num_medians,
        }, f, ensure_ascii=False, indent=2)
    print(f"  saved {MODEL_META.name}")

    return model_json


if __name__ == '__main__':
    main()
